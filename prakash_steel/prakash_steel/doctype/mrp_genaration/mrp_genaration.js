
frappe.ui.form.on("MRP Genaration", {
    refresh(frm) {
        // Add click handler for the MR Generation button field
        if (frm.fields_dict.mr_genaration) {
            frm.fields_dict.mr_genaration.$input.on("click", function () {
                generate_mrp_order_recommendations(frm);
            });
        }
    },
});

// Helper functions to enable/disable the MR Generation button
function disable_mr_generation_button(frm) {
    if (frm.fields_dict.mr_genaration) {
        frm.set_df_property("mr_genaration", "read_only", 1);
        // Also disable the button visually
        if (frm.fields_dict.mr_genaration.$input) {
            frm.fields_dict.mr_genaration.$input.prop("disabled", true);
            frm.fields_dict.mr_genaration.$input.addClass("disabled");
        }
    }
}

function enable_mr_generation_button(frm) {
    if (frm.fields_dict.mr_genaration) {
        frm.set_df_property("mr_genaration", "read_only", 0);
        // Also enable the button visually
        if (frm.fields_dict.mr_genaration.$input) {
            frm.fields_dict.mr_genaration.$input.prop("disabled", false);
            frm.fields_dict.mr_genaration.$input.removeClass("disabled");
        }
    }
}

function generate_mrp_order_recommendations(frm) {
    // Show confirmation dialog
    frappe.confirm(
        __("This will generate Material Request order recommendations for all items (buffer and non-buffer) by traversing all BOMs. This may take some time. Continue?"),
        function () {
            // Disable the button to prevent multiple clicks
            disable_mr_generation_button(frm);

            // Show progress
            frappe.show_progress(__("Generating MRP Order Recommendations"), 0, __("Queuing job..."));

            // Call the API to enqueue the calculation job
            frappe.call({
                method: "prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration.generate_mrp_order_recommendations",
                callback: function (r) {
                    if (r.message) {
                        if (r.message.error) {
                            frappe.hide_progress();
                            // Re-enable button on error
                            enable_mr_generation_button(frm);
                            frappe.msgprint({
                                title: __("Error"),
                                message: __("Error: {0}", [r.message.error]),
                                indicator: "red",
                            });
                        } else if (r.message.job_id) {
                            // Job queued successfully, start polling
                            const jobId = r.message.job_id;
                            frappe.show_progress(
                                __("Generating MRP Order Recommendations"),
                                0,
                                __("Job queued (ID: {0}). Starting background calculation...", [jobId])
                            );

                            // Show initial notification
                            frappe.show_alert({
                                message: __("MRP calculation job has been queued. Processing in background..."),
                                indicator: "blue",
                            }, 5);

                            poll_mrp_job_status(jobId, frm);
                        } else {
                            frappe.hide_progress();
                            // Re-enable button on error
                            enable_mr_generation_button(frm);
                            frappe.msgprint({
                                title: __("Error"),
                                message: __("Job ID not returned. Please try again."),
                                indicator: "red",
                            });
                        }
                    }
                },
                error: function (r) {
                    frappe.hide_progress();
                    // Re-enable button on error
                    enable_mr_generation_button(frm);
                    frappe.msgprint({
                        title: __("Error"),
                        message: __("An error occurred while queuing the job."),
                        indicator: "red",
                    });
                },
            });
        }
    );
}

function poll_mrp_job_status(jobId, frm) {
    // Poll for job status every 2 seconds
    const pollInterval = setInterval(function () {
        frappe.call({
            method: "prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration.get_mrp_job_status",
            args: {
                job_id: jobId,
            },
            callback: function (r) {
                if (r.message) {
                    const status = r.message.status;

                    if (status === "completed") {
                        clearInterval(pollInterval);
                        frappe.hide_progress();

                        // Get the result
                        get_mrp_job_result(jobId, frm);
                    } else if (status === "failed") {
                        clearInterval(pollInterval);
                        frappe.hide_progress();
                        frappe.msgprint({
                            title: __("Job Failed"),
                            message: __("Error: {0}", [r.message.error || "Unknown error"]),
                            indicator: "red",
                        });
                    } else if (status === "running") {
                        // Update progress message with job ID
                        const progressMsg = __("Processing... (Job ID: {0})", [jobId]);
                        frappe.show_progress(__("Generating MRP Order Recommendations"), 0, progressMsg);
                    } else if (status === "queued") {
                        // Update progress message with job ID
                        const progressMsg = __("Queued. Waiting to start... (Job ID: {0})", [jobId]);
                        frappe.show_progress(__("Generating MRP Order Recommendations"), 0, progressMsg);
                    } else {
                        // Unknown status
                        frappe.show_progress(__("Generating MRP Order Recommendations"), 0, __("Status: {0}", [status]));
                    }
                }
            },
            error: function (r) {
                clearInterval(pollInterval);
                frappe.hide_progress();
                // Re-enable button on error
                enable_mr_generation_button(frm);
                frappe.msgprint({
                    title: __("Error"),
                    message: __("An error occurred while checking job status."),
                    indicator: "red",
                });
            },
        });
    }, 2000); // Poll every 2 seconds

    // Set a maximum timeout (e.g., 1 hour)
    setTimeout(function () {
        clearInterval(pollInterval);
        frappe.hide_progress();
        // Re-enable button on timeout
        enable_mr_generation_button(frm);
        frappe.msgprint({
            title: __("Timeout"),
            message: __("Job is taking longer than expected. Please check the job status manually."),
            indicator: "orange",
        });
    }, 3600000); // 1 hour timeout
}

function get_mrp_job_result(jobId, frm) {
    frappe.call({
        method: "prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration.get_mrp_job_result",
        args: {
            job_id: jobId,
        },
        callback: function (r) {
            if (r.message) {
                if (r.message.error) {
                    // Re-enable button on error
                    enable_mr_generation_button(frm);
                    frappe.msgprint({
                        title: __("Error"),
                        message: __("Error: {0}", [r.message.error]),
                        indicator: "red",
                    });
                } else {
                    // Show success message for calculation
                    const net_order_recs = r.message.net_order_recommendations || {};
                    const items_with_rec = Object.keys(net_order_recs).filter(
                        item => net_order_recs[item] > 0
                    ).length;

                    // Log to browser console as well - show net order recommendations
                    console.log("MRP Net Order Recommendations:", r.message.net_order_recommendations);
                    console.log("MRP Base Order Recommendations:", r.message.order_recommendations);

                    // Log detailed breakdown for each item
                    if (r.message.detailed_info) {
                        console.log("\n" + "=".repeat(100));
                        console.log("MRP DETAILED BREAKDOWN FOR ALL ITEMS");
                        console.log("=".repeat(100));

                        // Sort items by net_order_rec (descending)
                        const detailedInfo = r.message.detailed_info;
                        const sortedItems = Object.keys(detailedInfo).sort((a, b) => {
                            const netRecA = detailedInfo[a].net_order_rec || 0;
                            const netRecB = detailedInfo[b].net_order_rec || 0;
                            if (netRecB !== netRecA) {
                                return netRecB - netRecA;
                            }
                            return a.localeCompare(b);
                        });

                        // Show summary first
                        console.log("\n" + "-".repeat(100));
                        console.log("SUMMARY (Items with Net Order Recommendation > 0)");
                        console.log("-".repeat(100));
                        const itemsWithRec = sortedItems.filter(item => {
                            const netRec = detailedInfo[item].net_order_rec || 0;
                            return netRec > 0;
                        });

                        itemsWithRec.forEach(itemCode => {
                            const info = detailedInfo[itemCode];
                            const netRec = info.net_order_rec || 0;
                            const finalRec = info.final_order_rec || 0;
                            const bufferFlag = info.buffer_flag || "Unknown";
                            console.log(`  ${itemCode} (${bufferFlag}): Net Order Rec = ${netRec} (Base: ${finalRec})`);
                        });

                        // Show detailed breakdown for all items
                        console.log("\n" + "=".repeat(100));
                        console.log("DETAILED BREAKDOWN FOR ALL ITEMS");
                        console.log("=".repeat(100));

                        sortedItems.forEach(itemCode => {
                            const info = detailedInfo[itemCode];
                            const breakdown = info.calculation_breakdown || "";

                            if (breakdown && breakdown.trim()) {
                                console.log(breakdown);
                            } else {
                                // Create a basic breakdown if not available
                                const netRec = info.net_order_rec || 0;
                                const finalRec = info.final_order_rec || 0;
                                const bufferFlag = info.buffer_flag || "Unknown";
                                const moq = info.moq || 0;
                                const batchSize = info.batch_size || 0;

                                console.log(`\n  Item: ${itemCode}`);
                                console.log(`  Type: ${bufferFlag}`);
                                console.log(`  Base Order Recommendation: ${finalRec}`);
                                console.log(`  Net Order Recommendation: ${netRec}`);
                                if (moq > 0) {
                                    console.log(`  MOQ: ${moq}`);
                                }
                                if (batchSize > 0) {
                                    console.log(`  Batch Size: ${batchSize}`);
                                }
                                console.log(`  Note: Detailed breakdown not available`);
                            }
                            console.log("-".repeat(100));
                        });

                        console.log("\n" + "=".repeat(100));
                        console.log(`Total Items: ${sortedItems.length}`);
                        console.log(`Items with Net Order Rec > 0: ${itemsWithRec.length}`);
                        console.log("=".repeat(100));
                    }

                    // Check if there are any items with net order recommendations > 0
                    if (items_with_rec === 0) {
                        // No items need Material Requests
                        // Re-enable button
                        enable_mr_generation_button(frm);
                        frappe.msgprint({
                            title: __("No Material Requests Needed"),
                            message: __(
                                "MRP calculation completed successfully!<br><br>" +
                                "<b>No items require Material Requests at this time.</b><br><br>" +
                                "All items have sufficient stock, WIP, Open PO, or Material Requests to cover their requirements.<br><br>" +
                                "Check server logs and console for detailed breakdown."
                            ),
                            indicator: "blue",
                        });
                    } else {
                        // Show success message and proceed with Material Request creation
                        frappe.msgprint({
                            title: __("Order Recommendations Calculated"),
                            message: __(
                                "Order recommendations calculated successfully!<br><br>" +
                                "Items with net order recommendations > 0: <b>{0}</b><br><br>" +
                                "Creating Material Requests now...",
                                [items_with_rec]
                            ),
                            indicator: "green",
                        });

                        // Now automatically create Material Requests
                        create_material_requests_automatically(frm, r.message.net_order_recommendations);
                    }
                }
            }
        },
        error: function (r) {
            // Re-enable button on error
            enable_mr_generation_button(frm);
            frappe.msgprint({
                title: __("Error"),
                message: __("An error occurred while retrieving job results."),
                indicator: "red",
            });
        },
    });
}

function create_material_requests_automatically(frm, net_order_recommendations) {
    if (!net_order_recommendations) {
        // Re-enable button if no recommendations
        enable_mr_generation_button(frm);
        frappe.msgprint({
            title: __("Error"),
            message: __("No order recommendations available to create Material Requests."),
            indicator: "red",
        });
        return;
    }

    // Show progress
    frappe.show_progress(__("Creating Material Requests"), 0, __("Queuing job..."));

    // Call the API to enqueue Material Request creation as background job
    frappe.call({
        method: "prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration.create_material_requests_automatically",
        args: {
            net_order_recommendations: net_order_recommendations,
        },
        callback: function (r) {
            if (r.message) {
                if (r.message.error) {
                    frappe.hide_progress();
                    // Re-enable button on error
                    enable_mr_generation_button(frm);
                    frappe.msgprint({
                        title: __("Error"),
                        message: __("Error: {0}", [r.message.error]),
                        indicator: "red",
                    });
                } else if (r.message.job_id) {
                    // Job queued successfully, start polling
                    const jobId = r.message.job_id;
                    frappe.show_progress(
                        __("Creating Material Requests"),
                        0,
                        __("Job queued (ID: {0}). Starting background process...", [jobId])
                    );

                    // Show initial notification
                    frappe.show_alert({
                        message: __("Material Request creation job has been queued. Processing in background..."),
                        indicator: "blue",
                    }, 5);

                    poll_mr_creation_job_status(jobId, frm);
                } else {
                    // Direct result (if not using background job)
                    frappe.hide_progress();
                    // Re-enable button when done
                    enable_mr_generation_button(frm);
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
                    console.log("Material Requests Created:", r.message.material_requests);
                }
            }
        },
        error: function (r) {
            frappe.hide_progress();
            // Re-enable button on error
            enable_mr_generation_button(frm);
            frappe.msgprint({
                title: __("Error"),
                message: __("An error occurred while creating Material Requests."),
                indicator: "red",
            });
        },
    });
}

function poll_mr_creation_job_status(jobId, frm) {
    let pollCount = 0;

    // Poll for job status every 2 seconds
    const pollInterval = setInterval(function () {
        pollCount++;

        frappe.call({
            method: "prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration.get_mrp_job_status",
            args: {
                job_id: jobId,
            },
            callback: function (r) {
                if (r.message) {
                    const status = r.message.status;

                    if (status === "completed") {
                        clearInterval(pollInterval);
                        frappe.hide_progress();

                        // Get the result - try from status response first, then fetch separately
                        let result = r.message.result;

                        // If result not in status response, fetch it separately
                        if (!result) {
                            frappe.call({
                                method: "prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration.get_mrp_job_result",
                                args: {
                                    job_id: jobId,
                                },
                                callback: function (r2) {
                                    if (r2.message && !r2.message.error) {
                                        result = r2.message;
                                        show_mr_creation_result(result, frm);
                                    } else {
                                        // Result not found, show generic success
                                        // Re-enable button
                                        enable_mr_generation_button(frm);
                                        frappe.msgprint({
                                            title: __("Success"),
                                            message: __("Material Request creation job completed successfully. Check 'RQ Job' list for details."),
                                            indicator: "green",
                                        });
                                    }
                                },
                            });
                        } else {
                            show_mr_creation_result(result, frm);
                        }
                    } else if (status === "failed") {
                        clearInterval(pollInterval);
                        frappe.hide_progress();
                        frappe.msgprint({
                            title: __("Job Failed"),
                            message: __("Error: {0}", [r.message.error || "Unknown error"]),
                            indicator: "red",
                        });
                    } else if (status === "running") {
                        // Show progress bar immediately
                        frappe.show_progress(__("Creating Material Requests"), 0, __("Processing..."));

                        // Fetch progress details
                        frappe.call({
                            method: "prakash_steel.prakash_steel.doctype.mrp_genaration.mrp_genaration.get_mr_creation_progress",
                            args: {
                                job_id: jobId,
                            },
                            callback: function (progressR) {
                                if (progressR.message && progressR.message.total > 0) {
                                    const progress = progressR.message;
                                    const percent = Math.max(0, Math.min(100, progress.percent || 0)); // Ensure 0-100
                                    const current = progress.current || 0;
                                    const total = progress.total || 0;
                                    const currentItem = progress.current_item || "";
                                    const successCount = progress.success_count || 0;
                                    const errorCount = progress.error_count || 0;

                                    // Show progress bar with item name (similar to deletion dialog)
                                    let progressMsg = "";
                                    if (currentItem) {
                                        progressMsg = __("Creating Material Request for {0}", [currentItem]);
                                    } else {
                                        progressMsg = __("Processing...");
                                    }

                                    // Show progress with percentage - ensure percent is between 0 and 100
                                    // Use at least 1% to ensure progress bar is visible (Frappe shows bar at 1%+)
                                    const displayPercent = Math.max(1, percent);
                                    frappe.show_progress(
                                        __("Creating Material Requests"),
                                        displayPercent,
                                        progressMsg + ` (${current}/${total}) - Success: ${successCount}, Failed: ${errorCount}`
                                    );
                                } else {
                                    // Fallback if progress not available yet
                                    frappe.show_progress(__("Creating Material Requests"), 0, __("Processing... (Job ID: {0})", [jobId]));
                                }
                            },
                        });
                    } else if (status === "queued") {
                        // Update progress message
                        const progressMsg = __("Queued. Waiting to start... (Job ID: {0})", [jobId]);
                        frappe.show_progress(__("Creating Material Requests"), 0, progressMsg);
                    } else {
                        // Unknown status, keep showing progress
                        frappe.show_progress(__("Creating Material Requests"), 0, __("Status: {0}", [status]));
                    }
                } else {
                    // No message, keep polling
                    frappe.show_progress(__("Creating Material Requests"), 0, __("Checking status... ({0})", [pollCount]));
                }
            },
            error: function (r) {
                clearInterval(pollInterval);
                frappe.hide_progress();
                // Re-enable button on error
                enable_mr_generation_button(frm);
                frappe.msgprint({
                    title: __("Error"),
                    message: __("An error occurred while checking job status: {0}", [r.message || "Unknown error"]),
                    indicator: "red",
                });
            },
        });
    }, 2000); // Poll every 2 seconds

    // Set a maximum timeout (e.g., 30 minutes)
    setTimeout(function () {
        clearInterval(pollInterval);
        frappe.hide_progress();
        // Re-enable button on timeout
        enable_mr_generation_button(frm);
        frappe.msgprint({
            title: __("Timeout"),
            message: __("Job is taking longer than expected. Please check the 'RQ Job' list (Job ID: {0}) to see the current status.", [jobId]),
            indicator: "orange",
        });
    }, 1800000); // 30 minutes timeout
}

function show_mr_creation_result(result, frm) {
    if (!result) {
        // Re-enable button
        enable_mr_generation_button(frm);
        frappe.msgprint({
            title: __("Success"),
            message: __("Material Request creation completed. Check 'RQ Job' list for details."),
            indicator: "green",
        });
        return;
    }

    const successCount = result.success_count || 0;
    const errorCount = result.error_count || 0;
    const errors = result.errors || [];
    const materialRequests = result.material_requests || [];

    // Re-enable button when Material Request creation is complete
    enable_mr_generation_button(frm);

    if (errorCount > 0) {
        // Show detailed message with errors
        let errorMsg = errors.slice(0, 10).join("<br>"); // Show first 10 errors
        if (errors.length > 10) {
            errorMsg += `<br><br>... and ${errors.length - 10} more error(s)`;
        }

        frappe.msgprint({
            title: __("Material Requests Created"),
            message: __(
                "<b>Success:</b> {0} Material Request(s) created<br>" +
                "<b>Failed:</b> {1} Material Request(s)<br><br>" +
                "<b>Errors:</b><br>{2}",
                [successCount, errorCount, errorMsg]
            ),
            indicator: errorCount > successCount ? "red" : "orange",
        });
    } else if (successCount > 0) {
        // Show success message
        frappe.msgprint({
            title: __("Success"),
            message: __(
                "Successfully created <b>{0}</b> Material Request(s)!<br><br>" +
                "Material Request IDs: {1}",
                [successCount, materialRequests.slice(0, 20).join(", ") + (materialRequests.length > 20 ? "..." : "")]
            ),
            indicator: "green",
        });
    } else {
        // No material requests created
        frappe.msgprint({
            title: __("No Material Requests Created"),
            message: __("No Material Requests were created. All items may already have sufficient stock or no order recommendations."),
            indicator: "blue",
        });
    }

    // Log to console
    console.log("Material Requests Created:", materialRequests);
}