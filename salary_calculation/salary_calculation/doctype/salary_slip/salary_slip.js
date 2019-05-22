// Copyright (c) 2019, BJJ and contributors
// For license information, please see license.txt

frappe.ui.form.on('Salary Slip', {
	refresh: function(frm) {

	},
	start_date: function(frm, dt, dn){
		if(frm.doc.start_date){
			frm.trigger("set_end_date");
		}
		if(frm.doc.start_date){

		frappe.call({
			method:"salary_calculation.salary_calculation.doctype.salary_slip.salary_slip.get_assigned_salary_structure",
			args:{'employee':frm.doc.employee,'on_date':frm.doc.start_date},
			callback: function (r) {
				if(r.message){
					console.log(r.message);
					frm.set_value('salary_structure',r.message)
				}


			}
	
	
		})

		}
	},
	employee:function(frm,dt,dn){
		if(frm.doc.start_date){
		frappe.call({
			method:"salary_calculation.salary_calculation.doctype.salary_slip.salary_slip.get_assigned_salary_structure",
			args:{'employee':frm.doc.employee,'on_date':frm.doc.start_date},
			callback: function (r) {
				if(r.message){
					console.log(r.message);
					frm.set_value('salary_structure',r.message)
				}


			}
	
	
		})
		}

	},
	salary_structure: function(frm){
		if(frm.doc.salary_structure){
			frappe.call({
				"method": "frappe.client.get",
				args: {
					doctype: "Salary Structure",
					name: frm.doc.salary_structure
				},
				callback: function (data) {
					frm.set_value("payroll_frequency", data.message.payroll_frequency)
				}
			});


		}
	},
	set_end_date: function(frm){
		frappe.call({
			method: 'erpnext.hr.doctype.payroll_entry.payroll_entry.get_end_date',
			args: {
				frequency: frm.doc.payroll_frequency,
				start_date: frm.doc.start_date
			},
			callback: function (r) {
				if (r.message) {
					frm.set_value('end_date', r.message.end_date);
					frm.set_value('total_working_days','30');
				}
			}
		})
	}
});


frappe.ui.form.on('Salary Detail', {
	earnings_remove: function(frm, dt, dn) {
		calculate_all(frm.doc, dt, dn);
	},
	deductions_remove: function(frm, dt, dn) {
		calculate_all(frm.doc, dt, dn);
	},
	amount: function(frm,dt,dn){
		console.log("test")
		calculate_all(frm.doc, dt, dn);

	}
})



var calculate_all = function(doc, dt, dn) {
	calculate_earning_total(doc, dt, dn);
	calculate_ded_total(doc, dt, dn);
	calculate_net_pay(doc, dt, dn);
}



// Calculate earning total
// ------------------------------------------------------------------------
var calculate_earning_total = function(doc, dt, dn, reset_amount) {
	console.log('earning')

	var tbl = doc.earnings || [];
	var total_earn = 0;
	for(var i = 0; i < tbl.length; i++){
		if(!tbl[i].do_not_include_in_total) {
			total_earn += flt(tbl[i].amount);

		}
	}
	doc.gross_pay = total_earn;
	refresh_many(['earnings', 'amount','gross_pay']);

}

// Calculate deduction total
// ------------------------------------------------------------------------
var calculate_ded_total = function(doc, dt, dn, reset_amount) {
	var tbl = doc.deductions || [];
	var total_ded = 0;
	for(var i = 0; i < tbl.length; i++){
		if(cint(tbl[i].depends_on_lwp) == 1) {
			tbl[i].amount = Math.round(tbl[i].default_amount)*(flt(doc.payment_days)/cint(doc.total_working_days)*100)/100;
		} else if(reset_amount && tbl[i].default_amount) {
			tbl[i].amount = tbl[i].default_amount;
		}
		if(!tbl[i].do_not_include_in_total) {
			total_ded += flt(tbl[i].amount);
		}
	}
	doc.total_deduction = total_ded;
	refresh_many(['deductions', 'total_deduction']);
}

// Calculate net payable amount
// ------------------------------------------------------------------------
var calculate_net_pay = function(doc, dt, dn) {
	doc.net_pay = flt(doc.gross_pay) - flt(doc.total_deduction);
	doc.rounded_total = Math.round(doc.net_pay);
	refresh_many(['net_pay', 'rounded_total']);
}

