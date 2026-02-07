# Production Qty Based on Child Stock - Calculation Logic

## For Item: ITEM-104395

### Overview
The "Production qty based on child stock" field shows how many units of the **parent item** (ITEM-104395) can be produced using the **allocated child stock**.

### Step-by-Step Calculation

#### Step 1: Calculate Child Requirement
**Location:** Line 1198 in `po_recomendation_for_psp.py`

```python
normalized_bom_qty = child_bom_qty / child_bom_quantity
child_requirement = ceil(or_with_moq_batch_size × normalized_bom_qty)
```

**From your screenshots:**
- Child Requirement = **5943** (for child item ITEM-104420)

#### Step 2: Allocate Child Stock (FIFO)
**Location:** Line 1347 in `po_recomendation_for_psp.py`

```python
available_stock = remaining_child_stock_fifo.get(child_item_code, 0)
stock_allocated = min(child_requirement, available_stock)
```

**From your screenshots:**
- Child Stock Available = **7000**
- Child Requirement = **5943**
- **Stock Allocated = min(5943, 7000) = 5943**

#### Step 3: Convert Child Stock to Parent Production Qty
**Location:** Line 1359 in `po_recomendation_for_psp.py`

```python
parent_per_child_factor = child_bom_qty / child_bom_quantity
production_qty_based_on_child_stock = ceil(stock_allocated × parent_per_child_factor)
```

**Calculation:**
- Stock Allocated = **5943**
- Production Qty = **8618**
- Therefore: **8618 = ceil(5943 × factor)**

**Solving for the BOM factor:**
- Factor = 8618 / 5943 ≈ **1.45**

This means:
- **child_bom_qty / child_bom_quantity ≈ 1.45**

### The Logic Explained

The formula converts **child stock quantity** back to **parent production quantity** using the **inverse of the BOM ratio**:

1. **Forward direction** (Parent → Child):
   - Parent order qty × (child_bom_qty / child_bom_quantity) = Child requirement
   - Example: If parent needs 4098 units and ratio is 1.45, child needs 5943 units

2. **Backward direction** (Child → Parent):
   - Child stock allocated × (child_bom_qty / child_bom_quantity) = Parent production qty
   - Example: If 5943 child units are allocated and ratio is 1.45, parent can produce 8618 units

### Why 8618?

**The calculation is:**
```
Production Qty = ceil(5943 × 1.45) = ceil(8617.35) = 8618
```

**The BOM ratio of 1.45 means:**
- For every **1 unit of parent** (ITEM-104395), you need **1.45 units of child** (ITEM-104420)
- Conversely, **1.45 units of child stock** can produce **1 unit of parent**
- So **5943 units of child stock** can produce **5943 / 1.45 ≈ 4098 units of parent**... wait, that doesn't match!

### ⚠️ CRITICAL ISSUE DETECTED

There's a **mathematical error** in the conversion formula!

**Understanding BOM Structure:**
- `child_bom_quantity` = Quantity of PARENT produced by BOM (typically 1)
- `child_bom_qty` = Quantity of CHILD needed in BOM (e.g., 1.45)

**Forward Calculation (Parent → Child):**
- To produce 1 parent, you need `child_bom_qty / child_bom_quantity` = 1.45 child
- Formula: `Child Requirement = Parent Order × (child_bom_qty / child_bom_quantity)`
- Example: 4098 parent × 1.45 = 5943 child ✓

**Backward Calculation (Child → Parent):**
- If you have 1 child, you can produce `child_bom_quantity / child_bom_qty` = 1/1.45 = 0.69 parent
- Formula should be: `Parent Production = Child Stock / (child_bom_qty / child_bom_quantity)`
- OR: `Parent Production = Child Stock × (child_bom_quantity / child_bom_qty)`
- Example: 5943 child ÷ 1.45 = 4098 parent ✓

**Current Code (WRONG):**
```python
# Line 1359 - This is INCORRECT!
production_qty = ceil(stock_allocated × (child_bom_qty / child_bom_quantity))
# Result: 5943 × 1.45 = 8618 ✗
```

**Correct Formula Should Be:**
```python
# Option 1: Using division
production_qty = ceil(stock_allocated / (child_bom_qty / child_bom_quantity))

# Option 2: Using inverse factor (preferred)
production_qty = ceil(stock_allocated × (child_bom_quantity / child_bom_qty))
# Result: 5943 × (1 / 1.45) = 5943 × 0.69 = 4098 ✓
```

### The Bug

The comment on line 1354 says:
> "Parent units per 1 child unit = BOM Item Qty / BOM Qty"

**This is mathematically incorrect!** 

The correct relationship is:
- **Child units per 1 parent unit** = BOM Item Qty / BOM Qty = 1.45
- **Parent units per 1 child unit** = BOM Qty / BOM Item Qty = 1/1.45 = 0.69

The code is using the **forward ratio** (child per parent) when it should use the **inverse ratio** (parent per child) for the backward conversion.

### Verification

From your screenshots:
- Child Requirement: **5943** (calculated correctly: 4098 × 1.45 = 5943) ✓
- Child Stock Allocated: **5943** (min of requirement and available stock) ✓
- Production Qty (Current): **8618** (5943 × 1.45) ✗ **WRONG!**
- Production Qty (Should be): **4098** (5943 ÷ 1.45) ✓ **CORRECT!**

**Conclusion:** Line 1359 has a **bug** - it multiplies by the BOM ratio instead of dividing (or multiplying by the inverse). This causes the production quantity to be inflated by a factor of (BOM ratio)².

