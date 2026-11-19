# GST Invoicing Notes

## Rates used on our invoices
- Standard goods and services: **18% GST** (split into CGST + SGST for intra-state, IGST for inter-state).
- The `gst_amount` column in the invoices table is simply 18% of `amount`.

## Mandatory invoice fields
- Supplier and customer GSTIN (15 characters; first two digits are the state code).
- Invoice number (unique, max 16 characters), date, HSN/SAC code, taxable value, tax breakup.

## Common reconciliation problems
- Wrong or missing customer GSTIN -> input tax credit is denied to the customer.
- Invoice amount in the ledger differs from the invoice PDF (rounding or discount applied twice).
- Duplicate invoice numbers after a system migration.

## Due dates
Our standard payment term is **30 days** from the issue date. After the due date an invoice moves to `overdue`.
