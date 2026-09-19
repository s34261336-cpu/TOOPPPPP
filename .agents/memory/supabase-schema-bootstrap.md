---
name: Supabase schema bootstrap
description: One-time setup constraint for the app's Supabase REST persistence.
---

The Supabase REST API key can read and write existing tables but cannot create the PostgreSQL schema. Apply the checked-in schema through Supabase SQL Editor before starting the Supabase-backed app.

**Why:** A missing table returns HTTP 404 from PostgREST, so the application cannot safely initialize the database from `SUPABASE_URL` and `SUPABASE_KEY` alone.

**How to apply:** Run the project's `supabase_schema.sql` once, then restart the application; its first successful commit imports the existing local catalog into Supabase.