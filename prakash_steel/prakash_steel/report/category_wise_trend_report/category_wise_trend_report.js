// Copyright (c) 2026, beetashoke chakraborty and contributors
// For license information, please see license.txt

frappe.query_reports["Category wise Trend Report"] = {
	"filters": [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			width: "80",
			reqd: 1,
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -7),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			width: "80",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "sku_type",
			label: __("SKU Type"),
			fieldtype: "Select",
			width: "80",
			reqd: 1,
			options: "FGMTA\nSFGMTA\nPTA\nPending SO\nOpen PO",
		}
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Apply color styling to category column
		if (column.fieldname === "category" && data && value) {
			let category = value.trim().toUpperCase();
			let bg = "";
			let textColor = "#000000";

			if (category === "BLACK") {
				bg = "#000000";
				textColor = "#FFFFFF";
			} else if (category === "RED") {
				bg = "#FF0000";
				textColor = "#FFFFFF";
			} else if (category === "YELLOW") {
				bg = "#FFFF00";
				textColor = "#000000";
			} else if (category === "GREEN") {
				bg = "#00FF00";
				textColor = "#000000";
			} else if (category === "WHITE") {
				bg = "#FFFFFF";
				textColor = "#000000";
			}

			if (bg) {
				return `<div style="
					background-color:${bg};
					border-radius:0px;
					padding:4px;
					text-align:center;
					font-weight:bold;
					color:${textColor};
				">
					${category}
				</div>`;
			}
		}

		return value;
	}
};

