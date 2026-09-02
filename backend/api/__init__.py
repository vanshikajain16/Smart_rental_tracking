"""FastAPI layer for the Smart Rental Tracking System.

Reads only the real artifacts produced by the pipeline stages:
  data/processed/pipeline_output.json          (Stage 1-4 per-asset records)
  data/processed/stage1_output.csv             (per-cycle is_flagged)
  data/processed/stage4_customer_aggregate.json(dealer renewal-risk signal)
  data/processed/customers.csv                 (Stage 5 reliability score / tier)
"""
