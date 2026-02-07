// // Copyright (c) 2025, beetashoke chakraborty and contributors
// // For license information, please see license.txt

// frappe.query_reports["PO Recomendation for PSP"] = {
// 	filters: [
// 		{
// 			fieldname: "sku_type",
// 			label: __("SKU Type"),
// 			fieldtype: "MultiSelectList",
// 			width: "80",
// 			get_data: function (txt) {
// 				let sku_types = [
// 					"BBMTA",

// 					"RBMTA",

// 					"BOTA",

// 					"PTA",

// 					"TRMTA",

// 				];
// 				let options = [];
// 				for (let sku of sku_types) {
// 					if (!txt || sku.toLowerCase().includes(txt.toLowerCase())) {
// 						options.push({
// 							value: sku,
// 							label: __(sku),
// 							description: "",
// 						});
// 					}
// 				}
// 				return options;
// 			},
// 		},
// 		{
// 			fieldname: "item_code",
// 			label: __("Item Code"),
// 			fieldtype: "Link",
// 			options: "Item",
// 			width: "80",
// 		},
// 	],

// 	onload: function (report) {
// 		// Hide buttons: Debug PO Calculation, Create Material Request, Create Material Request Automatically
// 		// These buttons are commented out but can be uncommented later if needed
// 		/*
// 		// Debug PO Calculation button
// 		report.page.add_inner_button(__("Debug PO Calculation"), function () {
// 			frappe.prompt(
// 				[
// 					{
// 						fieldname: "item_code",
// 						label: __("Item Code"),
// 						fieldtype: "Link",
// 						options: "Item",
// 						reqd: 1,
// 					},
// 				],
// 				function (values) {
// 					frappe.call({
// 						method: "prakash_steel.prakash_steel.report.po_recomendation_for_psp.po_recomendation_for_psp.debug_po_calculation",
// 						args: {
// 							item_code: values.item_code,
// 							filters: report.get_filter_values(),
// 						},
// 						callback: function (r) {
// 							if (r.message && r.message.error) {
// 								frappe.msgprint(__("Error: {0}", [r.message.error]));
// 							} else {
// 								console.log("Debug PO Calculation:", r.message);
// 								frappe.msgprint(__("Check browser console for details"));
// 							}
// 						},
// 					});
// 				},
// 				__("Debug PO Calculation"),
// 				__("Calculate")
// 			);
// 		});

// 		// Create Material Request button
// 		report.page.add_inner_button(__("Create Material Request"), function () {
// 			frappe.prompt(
// 				[
// 					{
// 						fieldname: "item_code",
// 						label: __("Item Code"),
// 						fieldtype: "Link",
// 						options: "Item",
// 						reqd: 1,
// 					},
// 					{
// 						fieldname: "qty",
// 						label: __("Quantity"),
// 						fieldtype: "Float",
// 						reqd: 1,
// 					},
// 				],
// 				function (values) {
// 					frappe.call({
// 						method: "prakash_steel.prakash_steel.report.po_recomendation_for_psp.po_recomendation_for_psp.create_material_request",
// 						args: {
// 							item_code: values.item_code,
// 							qty: values.qty,
// 						},
// 						callback: function (r) {
// 							if (r.message && r.message.error) {
// 								frappe.msgprint(__("Error: {0}", [r.message.error]));
// 							} else {
// 								frappe.msgprint(__("Material Request {0} created successfully", [r.message.material_request]));
// 								report.refresh();
// 							}
// 						},
// 					});
// 				},
// 				__("Create Material Request"),
// 				__("Create")
// 			);
// 		});

// 		// Create Material Request Automatically button
// 		report.page.add_inner_button(__("Create Material Request Automatically"), function () {
// 			frappe.confirm(
// 				__("This will create Material Requests for all items with Net Order Recommendation > 0. Continue?"),
// 				function () {
// 					// Show progress
// 					frappe.show_progress(__("Creating Material Requests"), 0, __("Processing..."));

// 					frappe.call({
// 						method: "prakash_steel.prakash_steel.report.po_recomendation_for_psp.po_recomendation_for_psp.create_material_requests_automatically",
// 						args: {
// 							filters: report.get_filter_values(),
// 						},
// 						callback: function (r) {
// 							frappe.hide_progress();
// 							if (r.message) {
// 								if (r.message.error_count > 0) {
// 									frappe.msgprint({
// 										title: __("Material Requests Created"),
// 										message: __(
// 											"Success: {0}<br>Failed: {1}<br><br>Errors:<br>{2}",
// 											[
// 												r.message.success_count,
// 												r.message.error_count,
// 												r.message.errors.join("<br>"),
// 											]
// 										),
// 										indicator: r.message.error_count > r.message.success_count ? "red" : "green",
// 									});
// 								} else {
// 									frappe.msgprint({
// 										title: __("Success"),
// 										message: __("Created {0} Material Request(s)", [r.message.success_count]),
// 										indicator: "green",
// 									});
// 								}
// 								report.refresh();
// 							}
// 						},
// 					});
// 				}
// 			);
// 		});
// 		*/
// 	},

// 	formatter: function (value, row, column, data, default_formatter) {
// 		value = default_formatter(value, row, column, data);

// 		// Background colors for On Hand Colour status
// 		if (column.fieldname === "on_hand_colour" && data && data.on_hand_colour) {
// 			let colour = data.on_hand_colour;
// 			let bg = "";
// 			let textColor = "#000000";

// 			if (colour === "BLACK") {
// 				bg = "#000000";
// 				textColor = "#FFFFFF";
// 			} else if (colour === "RED") {
// 				bg = "#FF0000";
// 				textColor = "#FFFFFF";
// 			} else if (colour === "YELLOW") {
// 				bg = "#FFFF00";
// 				textColor = "#000000";
// 			} else if (colour === "GREEN") {
// 				bg = "#00FF00";
// 				textColor = "#000000";
// 			} else if (colour === "WHITE") {
// 				bg = "#FFFFFF";
// 				textColor = "#000000";
// 			}

// 			if (bg) {
// 				return `<div style="
// 					background-color:${bg};
// 					border-radius:0px;
// 					padding:4px;
// 					text-align:center;
// 					font-weight:bold;
// 					color:${textColor};
// 				">
// 					${colour}
// 				</div>`;
// 			}
// 		}

// 		// Background colors for Child full-kit status
// 		if (column.fieldname === "child_full_kit_status" && data && data.child_full_kit_status) {
// 			let fullkitRaw = data.child_full_kit_status || "";
// 			let fullkit = fullkitRaw.toLowerCase();

// 			if (!fullkit) {
// 				return value;
// 			}

// 			let bg = "";
// 			let textColor = "#000000";
// 			let fullkitText = fullkitRaw;

// 			if (fullkit === "full-kit") {
// 				bg = "#4dff88"; // Green
// 				textColor = "#000000";
// 			} else if (fullkit === "partial") {
// 				bg = "#ffff99"; // Yellow
// 				textColor = "#000000";
// 			} else if (fullkit === "pending") {
// 				bg = "#ff9999"; // Red
// 				textColor = "#000000";
// 			}

// 			if (bg) {
// 				return `<div style="
// 					background-color:${bg};
// 					border-radius:0px;
// 					padding:4px;
// 					text-align:center;
// 					font-weight:bold;
// 					color:${textColor};
// 				">
// 					${fullkitText}
// 				</div>`;
// 			}
// 		}

// 		// Background colors for Child WIP/Open PO full-kit status
// 		if (column.fieldname === "child_wip_open_po_full_kit_status" && data && data.child_wip_open_po_full_kit_status) {
// 			let fullkitRaw = data.child_wip_open_po_full_kit_status || "";
// 			let fullkit = fullkitRaw.toLowerCase();

// 			if (!fullkit) {
// 				return value;
// 			}

// 			let bg = "";
// 			let textColor = "#000000";
// 			let fullkitText = fullkitRaw;

// 			if (fullkit === "full-kit") {
// 				bg = "#4dff88"; // Green
// 				textColor = "#000000";
// 			} else if (fullkit === "partial") {
// 				bg = "#ffff99"; // Yellow
// 				textColor = "#000000";
// 			} else if (fullkit === "pending") {
// 				bg = "#ff9999"; // Red
// 				textColor = "#000000";
// 			}

// 			if (bg) {
// 				return `<div style="
// 					background-color:${bg};
// 					border-radius:0px;
// 					padding:4px;
// 					text-align:center;
// 					font-weight:bold;
// 					color:${textColor};
// 				">
// 					${fullkitText}
// 				</div>`;
// 			}
// 		}

// 		return value;
// 	},
// };









// Copyright (c) 2025, beetashoke chakraborty and contributors
// For license information, please see license.txt

frappe.query_reports["PO Recomendation for PSP"] = {
	filters: [
		{
			fieldname: "purchase",
			label: __("Purchase"),
			fieldtype: "Check",
			default: 0,
			width: "80",
		},
		{
			fieldname: "sell",
			label: __("Sell"),
			fieldtype: "Check",
			default: 0,
			width: "80",
		},
		{
			fieldname: "buffer_flag",
			label: __("Buffer Flag"),
			fieldtype: "Check",
			default: 0,
			width: "80",
		},
		{
			fieldname: "sku_type",
			label: __("SKU Type"),
			fieldtype: "MultiSelectList",
			width: "80",
			get_data: function (txt) {
				// This will be overridden in onload to access report filter values
				return [];
			},
		},
		{
			fieldname: "item_code",
			label: __("Item Code"),
			fieldtype: "Link",
			options: "Item",
			width: "80",
		},
	],

	onload: function (report) {
		// Store report reference for SKU type filter
		let report_ref = report;

		// Update SKU type filter's get_data to use report reference
		if (report.page.fields_dict.sku_type) {
			let original_get_data = report.page.fields_dict.sku_type.df.get_data;
			report.page.fields_dict.sku_type.df.get_data = function (txt) {
				// Get current filter values from report
				let filter_values = report_ref.get_filter_values ? report_ref.get_filter_values() : {};

				let purchase = filter_values.purchase || 0;
				let sell = filter_values.sell || 0;
				let buffer_flag = filter_values.buffer_flag || 0;

				// Determine which SKU types to show based on Purchase/Sell and Buffer Flag selection
				let sku_types = [];
				if (purchase) {
					if (buffer_flag) {
						// Purchase + Buffer: PTA (RM with buffer)
						sku_types = ["PTA"];
					} else {
						// Purchase + Non-Buffer: PTO (RM without buffer)
						sku_types = ["PTO"];
					}
				} else if (sell) {
					if (buffer_flag) {
						// Sell + Buffer: FGMTA (FG with buffer), SFGMTA (INT with buffer)
						sku_types = ["FGMTA", "SFGMTA"];
					} else {
						// Sell + Non-Buffer: FGMTO (FG without buffer), SFGMTO (INT without buffer)
						sku_types = ["FGMTO", "SFGMTO"];
					}
				} else {
					// No selection: return empty array
					return [];
				}

				let options = [];
				for (let sku of sku_types) {
					if (!txt || sku.toLowerCase().includes(txt.toLowerCase())) {
						options.push({
							value: sku,
							label: __(sku),
							description: "",
						});
					}
				}
				return options;
			};
		}

		// Make Purchase and Sell mutually exclusive
		report.page.fields_dict.purchase.$input.on("change", function () {
			if (report.page.fields_dict.purchase.get_value()) {
				report.page.fields_dict.sell.set_value(0);
			}
			// Refresh SKU type filter
			if (report.page.fields_dict.sku_type) {
				report.page.fields_dict.sku_type.refresh();
			}
		});

		report.page.fields_dict.sell.$input.on("change", function () {
			if (report.page.fields_dict.sell.get_value()) {
				report.page.fields_dict.purchase.set_value(0);
			}
			// Refresh SKU type filter
			if (report.page.fields_dict.sku_type) {
				report.page.fields_dict.sku_type.refresh();
			}
		});

		// Refresh SKU type filter when Buffer Flag changes
		report.page.fields_dict.buffer_flag.$input.on("change", function () {
			if (report.page.fields_dict.sku_type) {
				report.page.fields_dict.sku_type.refresh();
			}
		});
		// Hide buttons: Debug PO Calculation, Create Material Request, Create Material Request Automatically
		// These buttons are commented out but can be uncommented later if needed
		/*
		// Debug PO Calculation button
		report.page.add_inner_button(__("Debug PO Calculation"), function () {
			frappe.prompt(
				[
					{
						fieldname: "item_code",
						label: __("Item Code"),
						fieldtype: "Link",
						options: "Item",
						reqd: 1,
					},
				],
				function (values) {
					frappe.call({
						method: "prakash_steel.prakash_steel.report.po_recomendation_for_psp.po_recomendation_for_psp.debug_po_calculation",
						args: {
							item_code: values.item_code,
							filters: report.get_filter_values(),
						},
						callback: function (r) {
							if (r.message && r.message.error) {
								frappe.msgprint(__("Error: {0}", [r.message.error]));
							} else {
								console.log("Debug PO Calculation:", r.message);
								frappe.msgprint(__("Check browser console for details"));
							}
						},
					});
				},
				__("Debug PO Calculation"),
				__("Calculate")
			);
		});

		// Create Material Request button
		report.page.add_inner_button(__("Create Material Request"), function () {
			frappe.prompt(
				[
					{
						fieldname: "item_code",
						label: __("Item Code"),
						fieldtype: "Link",
						options: "Item",
						reqd: 1,
					},
					{
						fieldname: "qty",
						label: __("Quantity"),
						fieldtype: "Float",
						reqd: 1,
					},
				],
				function (values) {
					frappe.call({
						method: "prakash_steel.prakash_steel.report.po_recomendation_for_psp.po_recomendation_for_psp.create_material_request",
						args: {
							item_code: values.item_code,
							qty: values.qty,
						},
						callback: function (r) {
							if (r.message && r.message.error) {
								frappe.msgprint(__("Error: {0}", [r.message.error]));
							} else {
								frappe.msgprint(__("Material Request {0} created successfully", [r.message.material_request]));
								report.refresh();
							}
						},
					});
				},
				__("Create Material Request"),
				__("Create")
			);
		});

		// Create Material Request Automatically button
		report.page.add_inner_button(__("Create Material Request Automatically"), function () {
			frappe.confirm(
				__("This will create Material Requests for all items with Net Order Recommendation > 0. Continue?"),
				function () {
					// Show progress
					frappe.show_progress(__("Creating Material Requests"), 0, __("Processing..."));

					frappe.call({
						method: "prakash_steel.prakash_steel.report.po_recomendation_for_psp.po_recomendation_for_psp.create_material_requests_automatically",
						args: {
							filters: report.get_filter_values(),
						},
						callback: function (r) {
							frappe.hide_progress();
							if (r.message) {
								if (r.message.error_count > 0) {
									frappe.msgprint({
										title: __("Material Requests Created"),
										message: __(
											"Success: {0}<br>Failed: {1}<br><br>Errors:<br>{2}",
											[
												r.message.success_count,
												r.message.error_count,
												r.message.errors.join("<br>"),
											]
										),
										indicator: r.message.error_count > r.message.success_count ? "red" : "green",
									});
								} else {
									frappe.msgprint({
										title: __("Success"),
										message: __("Created {0} Material Request(s)", [r.message.success_count]),
										indicator: "green",
									});
								}
								report.refresh();
							}
						},
					});
				}
			);
		});
		*/
		
		// Log calculation breakdown for each item in browser console
		// This will show the detailed breakdown similar to MRP generation
		function logCalculationBreakdowns() {
			setTimeout(function() {
				try {
					// Get report data
					let data = report.data || [];
					
					if (data && data.length > 0) {
						console.log("\n" + "=".repeat(100));
						console.log("PO RECOMMENDATION FOR PSP - CALCULATION BREAKDOWN");
						console.log("=".repeat(100) + "\n");
						
						// Track items we've already logged (to avoid duplicates from child rows)
						let logged_items = new Set();
						
						data.forEach(function (row, index) {
							if (row && row.item_code && !logged_items.has(row.item_code)) {
								logged_items.add(row.item_code);
								
								// Log the breakdown if available
								if (row.calculation_breakdown) {
									console.log(row.calculation_breakdown);
									console.log("-".repeat(100));
								}
							}
						});
						
						console.log("\n" + "=".repeat(100));
						console.log("END OF CALCULATION BREAKDOWN");
						console.log("=".repeat(100) + "\n");
					}
				} catch (e) {
					console.error("Error logging calculation breakdown:", e);
				}
			}, 2000); // Wait for data to load
		}
		
		// Log when report loads
		logCalculationBreakdowns();
		
		// Also log when report refreshes
		if (report.refresh) {
			let originalRefresh = report.refresh;
			report.refresh = function() {
				let result = originalRefresh.apply(this, arguments);
				setTimeout(logCalculationBreakdowns, 2000);
				return result;
			};
		}
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Background colors for On Hand Colour status
		if (column.fieldname === "on_hand_colour" && data && data.on_hand_colour) {
			let colour = data.on_hand_colour;
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

		// Background colors for Child full-kit status
		if (column.fieldname === "child_full_kit_status" && data && data.child_full_kit_status) {
			let fullkitRaw = data.child_full_kit_status || "";
			let fullkit = fullkitRaw.toLowerCase();

			if (!fullkit) {
				return value;
			}

			let bg = "";
			let textColor = "#000000";
			let fullkitText = fullkitRaw;

			if (fullkit === "full-kit") {
				bg = "#4dff88"; // Green
				textColor = "#000000";
			} else if (fullkit === "partial") {
				bg = "#ffff99"; // Yellow
				textColor = "#000000";
			} else if (fullkit === "pending") {
				bg = "#ff9999"; // Red
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
					${fullkitText}
				</div>`;
			}
		}

		// Background colors for Child WIP/Open PO full-kit status
		if (column.fieldname === "child_wip_open_po_full_kit_status" && data && data.child_wip_open_po_full_kit_status) {
			let fullkitRaw = data.child_wip_open_po_full_kit_status || "";
			let fullkit = fullkitRaw.toLowerCase();

			if (!fullkit) {
				return value;
			}

			let bg = "";
			let textColor = "#000000";
			let fullkitText = fullkitRaw;

			if (fullkit === "full-kit") {
				bg = "#4dff88"; // Green
				textColor = "#000000";
			} else if (fullkit === "partial") {
				bg = "#ffff99"; // Yellow
				textColor = "#000000";
			} else if (fullkit === "pending") {
				bg = "#ff9999"; // Red
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
					${fullkitText}
				</div>`;
			}
		}

		return value;
	},
};