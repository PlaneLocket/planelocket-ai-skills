---
name: inventree-inventory
description: Answer questions about electronic components, parts, quantities, availability, and storage locations in the household InvenTree inventory.
---

# InvenTree Inventory

## Purpose

Help the user find parts in the household InvenTree inventory,
determine available quantities, and identify storage locations.

Use actual InvenTree records rather than general knowledge
when answering questions about owned inventory.

## Available tools

- `search_inventory_parts`: Search the InvenTree parts catalog.
  - Requires `query`, a string containing a part name,
    model number, or keyword.
  - Returns matching part records and their IDs.
  - A catalog match does not establish stock availability.

- `get_inventory_stock`: Retrieve stock records for a part.
  - Requires `part_id`, an integer obtained from
    `search_inventory_parts`.
  - Returns stock quantities, allocations, and locations.

  ## Investigation workflow

To answer questions about owned parts:

1. Call `search_inventory_parts` using the requested part name,
   model number, or keyword.
2. Examine the returned candidates and identify relevant matches.
3. For each relevant part, call `get_inventory_stock`
   using its returned part ID.
4. Calculate available quantity for each stock record as
   `quantity - allocated`.
5. Report quantities and storage locations using the stock records.
6. If multiple distinct parts match, identify them separately
   before reporting any combined total.

   ## Important rules

- Never invent part IDs, quantities, or storage locations.
- Use part IDs returned by InvenTree searches.
- Distinguish catalog matches from confirmed stock.
- Do not assume a cataloged part has inventory on hand.
- Do not count allocated stock as available.
- Preserve distinctions between different part variants,
  packages, and configurations.
- Do not combine quantities for unrelated or incompatible parts.
- Prefer the full `location_detail.pathstring` when available.
- If no matching parts or stock records are found, say so.
- Base inventory claims on actual InvenTree tool results.
- Inventory access is read-only. Do not claim to modify stock.