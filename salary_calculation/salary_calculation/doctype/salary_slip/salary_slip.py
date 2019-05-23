# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe, erpnext
import datetime
import json

from frappe.utils import add_days, cint, cstr, flt, getdate, rounded, date_diff, money_in_words, getdate
from frappe.model.naming import make_autoname

from frappe import msgprint, _
from erpnext.hr.doctype.payroll_entry.payroll_entry import get_start_end_dates
from erpnext.hr.doctype.employee.employee import get_holiday_list_for_employee
from erpnext.utilities.transaction_base import TransactionBase
from frappe.utils.background_jobs import enqueue
from erpnext.hr.doctype.additional_salary.additional_salary import get_additional_salary_component
from erpnext.hr.doctype.employee_benefit_application.employee_benefit_application import get_benefit_component_amount
from erpnext.hr.doctype.employee_benefit_claim.employee_benefit_claim import get_benefit_claim_amount, get_last_payroll_period_benefits

class SalarySlip(TransactionBase):
	def __init__(self, *args, **kwargs):
		super(SalarySlip, self).__init__(*args, **kwargs)
		self.series = 'Sal Slip/{0}/.#####'.format(self.employee)
		self.whitelisted_globals = {
			"int": int,
			"float": float,
			"long": int,
			"round": round,
			"date": datetime.date,
			"getdate": getdate
		}

	def autoname(self):
		self.name = make_autoname(self.series)

	def validate(self):
		self.total_working_days=30
		self.status = self.get_status()
		self.validate_dates()
		self.check_existing()
		self.get_attendance()
		self.get_lwp()
		self.sum_components()
		self.assign_salary_structure()

	def validate_dates(self):
		if date_diff(self.end_date, self.start_date) < 0:
			frappe.throw(_("To date cannot be before From date"))


	def get_status(self):
		if self.docstatus == 0:
			status = "Draft"
		elif self.docstatus == 1:
			status = "Submitted"
		elif self.docstatus == 2:
			status = "Cancelled"
		return status

	def assign_salary_structure(self):
		if self.start_date:
			self.salary_structure=get_assigned_salary_structure(self.employee,self.start_date)
			self.payroll_frequency=frappe.db.get_value("Salary Structure",self.salary_structure,"payroll_frequency")
	def check_existing(self):
		ret_exist = frappe.db.sql("""select name from `tabSalary Slip`
					where start_date = %s and end_date = %s and docstatus != 2
					and employee = %s and name != %s""",
					(self.start_date, self.end_date, self.employee, self.name))
		if ret_exist:
			self.employee = ''
			frappe.throw(_("Salary Slip of employee {0} already created for this period").format(self.employee))

	def get_attendance(self):
		basic_amount=0
		days=0
		att_doc1=frappe.db.sql("""select count(name) as count from `tabAttendance` where attendance_hour='8' and employee=%s and docstatus=1 and status='Present' and attendance_date between %s and %s""",(self.employee,self.start_date,self.end_date),as_dict=1)
		if att_doc1:
			rate=get_salary_structure_rate(self,'8')
			basic_amount += flt(att_doc1[0].count)*8*flt(rate)
			days += flt(att_doc1[0].count)
		att_doc2=frappe.db.sql("""select count(name) as count from `tabAttendance` where attendance_hour='12' and employee=%s and docstatus=1 and status='Present' and attendance_date between %s and %s""",(self.employee,self.start_date,self.end_date),as_dict=1)
		if att_doc2:
			rate=get_salary_structure_rate(self,'12')
			basic_amount += flt(att_doc2[0].count)*12*flt(rate)
			days += flt(att_doc2[0].count)
		att_doc3=frappe.db.sql("""select count(name) as count from `tabAttendance` where attendance_hour='16' and employee=%s and docstatus=1 and status='Present' and attendance_date between %s and %s""",(self.employee,self.start_date,self.end_date),as_dict=1)
		if att_doc3:
			rate=get_salary_structure_rate(self,'16')
			basic_amount += flt(att_doc3[0].count)*16*flt(rate)
			days += flt(att_doc3[0].count)
		remain_days=30-days
		rate=get_salary_structure_rate(self,'8')
		basic_amount += flt(remain_days)*8*flt(rate)
		

		frappe.errprint("Basic Amount"+str(basic_amount))

		add_base_component(self,basic_amount)

	def get_lwp(self):
		holidays = self.get_holidays_for_employee(self.start_date, self.end_date)
		working_days = date_diff(self.end_date, self.start_date) + 1
		actual_lwp = self.calculate_lwp(holidays, working_days)
		self.leave_without_pay=actual_lwp
		self.payment_days=flt(self.total_working_days)-flt(actual_lwp)
		rate=get_salary_structure_rate(self,'8')
		add_deduction_component(self,flt(actual_lwp)*8*flt(rate),'Leave Deduction')

	def get_holidays_for_employee(self, start_date, end_date):
		holiday_list = get_holiday_list_for_employee(self.employee)
		holidays = frappe.db.sql_list('''select holiday_date from `tabHoliday`
			where
				parent=%(holiday_list)s
				and holiday_date >= %(start_date)s
				and holiday_date <= %(end_date)s''', {
					"holiday_list": holiday_list,
					"start_date": start_date,
					"end_date": end_date
				})

		holidays = [cstr(i) for i in holidays]

		return holidays

	def calculate_lwp(self, holidays, working_days):
		lwp = 0
		holidays = "','".join(holidays)
		for d in range(working_days):
			dt = add_days(cstr(getdate(self.start_date)), d)
			leave = frappe.db.sql("""
				select t1.name, t1.half_day
				from `tabLeave Application` t1, `tabLeave Type` t2
				where t2.name = t1.leave_type
				and t2.is_lwp = 1
				and t1.docstatus = 1
				and t1.employee = %(employee)s
				and CASE WHEN t2.include_holiday != 1 THEN %(dt)s not in ('{0}') and %(dt)s between from_date and to_date and ifnull(t1.salary_slip, '') = ''
				WHEN t2.include_holiday THEN %(dt)s between from_date and to_date and ifnull(t1.salary_slip, '') = ''
				END
				""".format(holidays), {"employee": self.employee, "dt": dt})
			if leave:
				lwp = cint(leave[0][1]) and (lwp + 0.5) or (lwp + 1)
		frappe.msgprint(str(lwp))
		return lwp

	def sum_components(self):
		gross_pay=0
		total_deduction=0
		net_pay=0
		disable_rounded_total = cint(frappe.db.get_value("Global Defaults", None, "disable_rounded_total"))
		if self.earnings:
			for earn in self.earnings:
				gross_pay += flt(earn.amount)

		if self.deductions:
			for ded in self.deductions:
				total_deduction += flt(ded.amount)
		
		net_pay = gross_pay - total_deduction
		self.net_pay=net_pay
		self.gross_pay=gross_pay
		self.total_deduction=total_deduction
		self.rounded_total = rounded(self.net_pay,
			self.precision("net_pay") if disable_rounded_total else 0)
	
		

			
def add_base_component(self,amount):
	struct_dict=[]
	struct_row = {}
	component = frappe.get_doc("Salary Component", 'Basic')
	self.append('earnings', {
		'amount': amount,
		'default_amount': amount,
		'salary_component' : component.salary_component,
		'do_not_include_in_total' : component.do_not_include_in_total,
		'is_tax_applicable': component.is_tax_applicable,
		'is_flexible_benefit': component.is_flexible_benefit,
		'variable_based_on_taxable_salary': component.variable_based_on_taxable_salary
	})
	frappe.errprint(str(self.earnings))


	

def add_deduction_component(self,amount,component):
	struct_dict=[]
	struct_row = {}
	component = frappe.get_doc("Salary Component",component)
	self.append('deductions', {
		'amount': amount,
		'default_amount': amount,
		'depends_on_lwp' : component.depends_on_lwp,
		'salary_component' : component.salary_component,
		'do_not_include_in_total' : component.do_not_include_in_total,
		'is_tax_applicable': component.is_tax_applicable,
		'is_flexible_benefit': component.is_flexible_benefit,
		'variable_based_on_taxable_salary': component.variable_based_on_taxable_salary
	})
	frappe.errprint(str(self.deductions))


def get_salary_structure_rate(self,hour):
	ss_rate=frappe.db.sql("""select sshw.hourly as rate from `tabSalary Structure Hour Wise` as sshw inner join `tabSalary Structure Assignment` as ssa on sshw.parent=ssa.name where ssa.from_date<=%s and ssa.employee=%s and sshw.work_hour=%s""",(self.start_date,self.employee,hour),as_dict=1)
	#frappe.errprint("ss_rate"+str(ss_rate))
	if ss_rate:
		return ss_rate[0].rate
	else:
		return 0

@frappe.whitelist()
def get_assigned_salary_structure(employee, on_date):
	if not employee or not on_date:
		return None
	salary_structure = frappe.db.sql("""
		select salary_structure from `tabSalary Structure Assignment`
		where employee=%(employee)s
		and docstatus = 1
		and %(on_date)s >= from_date order by from_date desc limit 1""", {
			'employee': employee,
			'on_date': on_date,
		})
	return salary_structure[0][0] if salary_structure else None
