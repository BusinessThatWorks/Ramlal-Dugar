// Copyright (c) 2026, beetashoke chakraborty and contributors
// For license information, please see license.txt

frappe.query_reports["SKU wise Trend Report"] = {
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
			options: "FGMTA\nSFGMTA\nPTA",
		},
		{
			fieldname: "item_code",
			label: __("Item Code"),
			fieldtype: "MultiSelectList",
			width: "80",
			options: "Item",
			get_data: function (txt) {
				return frappe.db.get_link_options("Item", txt);
			},
		}
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Apply color styling to date columns (columns that start with "date_")
		if (column.fieldname && column.fieldname.startsWith("date_") && data && value) {
			let colour = value.trim().toUpperCase();
			let bg = "";
			let textColor = "#000000";

			if (colour === "BLACK") {
				bg = "#000000";
				textColor = "#FFFFFF";
			} else if (colour === "RED") {
				bg = "#FF0000";
				textColor = "#FFFFFF";
			} else if (colour === "YELLOW") {
				bg = "#FFFF00";
				textColor = "#000000";
			} else if (colour === "GREEN") {
				bg = "#00FF00";
				textColor = "#000000";
			} else if (colour === "WHITE") {
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
					${colour}
				</div>`;
			}
		}

		return value;
	}
};
