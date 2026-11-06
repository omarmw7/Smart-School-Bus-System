-- Run once in the Supabase SQL editor.
create table if not exists admins (
  admin_id      int4 generated always as identity primary key,
  email         text unique not null,
  name          text,
  password_hash text not null,
  created_at    timestamptz default now()
);

-- Lock every table so the public anon key can't read it.
-- The Flask server uses the service_role key, which bypasses RLS.
alter table admins          enable row level security;
alter table students        enable row level security;
alter table buses           enable row level security;
alter table attendance_logs enable row level security;
