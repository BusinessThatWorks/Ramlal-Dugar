// Prakash Steel Planning Dashboard
// Updated: Feb 7, 2025 - Changed to FGMTA, SFGMTA, PTA
// Shows:
// - On Hand Status pies for SKU types (FGMTA, SFGMTA, PTA)
// - Pending SO Status pie (by order_status colour)
// - Open PO Status pie (currently all BLACK)

frappe.pages['prakash-steel-planni'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Prakash Steel Planning Dashboard',
		single_column: true,
	});

	// Main container
	const $container = $(`
		<div class="planning-dashboard" style="padding: 15px;">
			<div class="charts-grid" style="
				display: grid;
				grid-template-columns: repeat(3, 1fr);
				gap: 16px;
			"></div>
		</div>
	`);

	page.main.empty();
	page.main.append($container);

	const $chartsContainer = $container.find('.charts-grid');

	page.set_indicator(__('Loading chart data...'), 'blue');

	const afterChartReady = () => load_all_charts(page, $chartsContainer);

	// Ensure Chart.js is available
	if (typeof Chart === 'undefined') {
		frappe.require('https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js', afterChartReady);
	} else {
		afterChartReady();
	}
};

function load_all_charts(page, $chartsContainer) {
	const colorMap = getColorMap();

	Promise.all([
		new Promise((resolve, reject) => {
			frappe.call({
				method: 'prakash_steel.prakash_steel.page.prakash_steel_planni.prakash_steel_planni.get_sku_type_on_hand_status',
				args: { filters: {} },
				callback: resolve,
				error: reject,
			});
		}),
		new Promise((resolve, reject) => {
			frappe.call({
				method: 'prakash_steel.prakash_steel.page.prakash_steel_planni.prakash_steel_planni.get_pending_so_status',
				callback: resolve,
				error: reject,
			});
		}),
		new Promise((resolve, reject) => {
			frappe.call({
				method: 'prakash_steel.prakash_steel.page.prakash_steel_planni.prakash_steel_planni.get_open_po_status',
				callback: resolve,
				error: reject,
			});
		}),
	])
		.then(([skuRes, pendingSoRes, openPoRes]) => {
			page.clear_indicator();

			console.log('[PLANNING DASHBOARD] ====== API RESPONSES ======');
			console.log('[PLANNING DASHBOARD] SKU Type Response:', skuRes);
			console.log('[PLANNING DASHBOARD] Pending SO Response:', pendingSoRes);
			console.log('[PLANNING DASHBOARD] Open PO Response:', openPoRes);

			// 1) SKU type pies
			if (skuRes && skuRes.message) {
				const skuData = skuRes.message;
				console.log('[PLANNING DASHBOARD] SKU Data received:', skuData);
				console.log('[PLANNING DASHBOARD] Version: Updated Feb 7, 2025 - FGMTA, SFGMTA, PTA only');
				const skuTypes = ['FGMTA', 'SFGMTA', 'PTA'];

				skuTypes.forEach((sku) => {
					console.log(`[PLANNING DASHBOARD] Checking ${sku}:`, {
						exists: !!skuData[sku],
						hasColours: !!(skuData[sku] && skuData[sku].colours),
						coloursLength: skuData[sku] && skuData[sku].colours ? skuData[sku].colours.length : 0,
						data: skuData[sku]
					});
					
					if (skuData[sku] && skuData[sku].colours && skuData[sku].colours.length > 0) {
						console.log(`[PLANNING DASHBOARD] ✓ Rendering ${sku} chart:`, skuData[sku]);
						console.log(`[PLANNING DASHBOARD] ${sku} - Total: ${skuData[sku].total_items}, Colours:`, skuData[sku].colours);
						const $card = createChartCard(sku, skuData[sku], colorMap);
						$chartsContainer.append($card);
						renderPieChart(sku, skuData[sku], colorMap);
					} else {
						console.log(`[PLANNING DASHBOARD] ✗ ${sku} - Skipping (no data or empty colours)`, {
							hasData: !!skuData[sku],
							hasColours: !!(skuData[sku] && skuData[sku].colours),
							coloursLength: skuData[sku] && skuData[sku].colours ? skuData[sku].colours.length : 0
						});
					}
				});
			} else {
				console.log('[PLANNING DASHBOARD] No SKU data received');
			}

			// 2) Pending SO Status pie
			if (pendingSoRes && pendingSoRes.message && pendingSoRes.message.colours && pendingSoRes.message.colours.length) {
				console.log('[PLANNING DASHBOARD] Rendering Pending SO Status chart:', pendingSoRes.message);
				console.log(`[PLANNING DASHBOARD] Pending SO - Total: ${pendingSoRes.message.total_orders}, Colours:`, pendingSoRes.message.colours);
				const $card = createChartCard('Pending SO Status', pendingSoRes.message, colorMap);
				$chartsContainer.append($card);
				renderPieChart('Pending SO Status', pendingSoRes.message, colorMap);
			} else {
				console.log('[PLANNING DASHBOARD] No Pending SO data or empty colours');
			}

			// 3) Open PO Status pie (all black for now)
			if (openPoRes && openPoRes.message) {
				console.log('[PLANNING DASHBOARD] Rendering Open PO Status chart:', openPoRes.message);
				const $card = createChartCard('Open PO Status', openPoRes.message, colorMap);
				$chartsContainer.append($card);
				renderPieChart('Open PO Status', openPoRes.message, colorMap);
			} else {
				console.log('[PLANNING DASHBOARD] No Open PO data received');
			}

			if ($chartsContainer.children().length === 0) {
				$chartsContainer.append(`
					<div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: #7f8c8d;">
						<i class="fa fa-info-circle" style="font-size: 2rem; margin-bottom: 12px;"></i>
						<div>${__('No data available')}</div>
					</div>
				`);
			}
		})
		.catch((err) => {
			console.error('Error loading planning dashboard charts:', err);
			page.clear_indicator();
			$chartsContainer.append(`
				<div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: #e74c3c;">
					<i class="fa fa-exclamation-triangle" style="font-size: 2rem; margin-bottom: 12px;"></i>
					<div>${__('Error loading data')}</div>
				</div>
			`);
		});
}

function getColorMap() {
	return {
		BLACK: '#000000',
		RED: '#ff0000',
		YELLOW: '#ffcc00', // Deeper yellow color
		GREEN: '#4dff88',
		WHITE: '#d3d3d3', // Grayish white for better visibility
	};
}

function createChartCard(key, data, colorMap) {
	const title = key.includes('Status') ? key : `${key} On Hand Status`;
	const chartId = key.replace(/\s+/g, '-');

	const $card = $(`
		<div class="chart-card" style="
			background:#fff;
			border-radius:8px;
			padding:16px;
			box-shadow:0 2px 8px rgba(0,0,0,0.1);
			position:relative;
		">
			<h3 style="
				margin:0 0 8px 0;
				font-size:1rem;
				font-weight:600;
				color:#2c3e50;
				text-align:center;
			">${title}</h3>
			<div style="position:relative;height:180px;margin-bottom:12px;">
				<canvas id="chart-${chartId}" style="max-height:180px;"></canvas>
			</div>
			<div class="chart-legend-${chartId}" style="
				display:flex;
				gap:12px;
				justify-content:center;
				margin-top:8px;
			">
				<div class="legend-left" style="display:flex;flex-direction:column;gap:6px;"></div>
				<div class="legend-right" style="display:flex;flex-direction:column;gap:6px;"></div>
			</div>
		</div>
	`);

	// Calculate and display total
	const total = data.total_items || data.total_orders || (data.colours ? data.colours.reduce((sum, c) => sum + c.count, 0) : 0);

	const $legend = $card.find(`.chart-legend-${chartId}`);
	const $legendLeft = $legend.find('.legend-left');
	const $legendRight = $legend.find('.legend-right');

	// Add Total to the bottom left corner of the card
	const $totalItem = $(`
		<div style="
			position:absolute;
			bottom:8px;
			left:16px;
		">
			<span style="
				color:#0066cc;
				font-size:0.9rem;
				font-weight:600;
			">Total: ${total}</span>
		</div>
	`);
	$card.append($totalItem);

	// Define middle and right column colors
	const middleColors = ['BLACK', 'RED', 'WHITE'];
	const rightColors = ['YELLOW', 'GREEN'];
	
	// Create a map of existing colors from data
	const colorDataMap = {};
	if (data.colours && data.colours.length) {
		data.colours.forEach((c) => {
			colorDataMap[c.name] = c;
		});
	}
	
	// Helper function to create legend item
	const createLegendItem = (colorName) => {
		const colorData = colorDataMap[colorName] || { name: colorName, count: 0, percentage: 0 };
		const isHidden = colorData.count === 0;
		return $(`
			<div style="
				display:flex;
				align-items:center;
				gap:5px;
				padding:4px 8px;
				border-radius:3px;
				min-height:24px;
				opacity:${isHidden ? '0' : '1'};
				pointer-events:${isHidden ? 'none' : 'auto'};
			">
				<div style="
					width:12px;
					height:12px;
					background:${colorMap[colorName] || '#ccc'};
					border-radius:2px;
					border:1px solid #ddd;
				"></div>
				<span style="color:#000000;font-size:0.75rem;font-weight:bold;">${colorData.count}</span>
				<span style="color:#000000;font-size:0.7rem;"><strong>(${colorData.percentage}%)</strong></span>
			</div>
		`);
	};
	
	// Always show all left column colors (BLACK, RED, WHITE)
	middleColors.forEach((colorName) => {
		$legendLeft.append(createLegendItem(colorName));
	});
	
	// Always show all right column colors (YELLOW, GREEN)
	rightColors.forEach((colorName) => {
		$legendRight.append(createLegendItem(colorName));
	});

	return $card;
}

function renderPieChart(key, data, colorMap) {
	const chartId = key.replace(/\s+/g, '-');
	const canvas = document.getElementById(`chart-${chartId}`);
	if (!canvas || !data || !data.colours) {
		console.log(`[PLANNING DASHBOARD] Cannot render ${key}: canvas=${!!canvas}, data=${!!data}, colours=${!!(data && data.colours)}`);
		return;
	}

	if (typeof Chart === 'undefined') {
		console.warn('[PLANNING DASHBOARD] Chart.js not available');
		return;
	}

	const ctx = canvas.getContext('2d');
	const labels = data.colours.map((c) => c.name);
	const values = data.colours.map((c) => c.count);
	const colors = data.colours.map((c) => colorMap[c.name] || '#ccc');

	console.log(`[PLANNING DASHBOARD] Rendering pie chart for ${key}:`);
	console.log(`  Labels:`, labels);
	console.log(`  Values:`, values);
	console.log(`  Colors:`, colors);
	console.log(`  Total:`, values.reduce((a, b) => a + b, 0));

	if (window[`chart_${chartId}`]) {
		window[`chart_${chartId}`].destroy();
	}

	window[`chart_${chartId}`] = new Chart(ctx, {
		type: 'pie',
		data: {
			labels,
			datasets: [
				{
					data: values,
					backgroundColor: colors,
					borderColor: '#fff',
					borderWidth: 2,
				},
			],
		},
		options: {
			responsive: true,
			maintainAspectRatio: true,
			plugins: {
				legend: { display: false },
				tooltip: {
					callbacks: {
						label: (ctx) => {
							const label = ctx.label || '';
							const value = ctx.parsed || 0;
							const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
							// Show rounded percentage (whole number)
							const pct = total ? Math.round((value / total) * 100) : 0;
							return `${label}: ${value} (${pct}%)`;
						},
					},
				},
			},
		},
	});
}








