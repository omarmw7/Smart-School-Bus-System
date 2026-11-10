-- ------------------------------------------------------------
-- 0) الجداول الأساسية (أُخذت أعمدتها من الكود). إن وُجدت مسبقًا لا تُغيَّر.
--    تحقق من أنها تطابق قاعدة بياناتك قبل الاعتماد عليها.
-- ------------------------------------------------------------
create table if not exists buses (
  bus_id       int4 generated always as identity primary key,
  driver_name  text not null,
  trip_status  text not null default 'idle'
               check (trip_status in ('idle', 'on_route', 'finished')),
  current_lat  float8,
  current_lng  float8,
  last_updated timestamptz
);

create table if not exists students (
  student_id     int4 generated always as identity primary key,
  name           text not null,
  fingerprint_id int4 not null,
  parent_phone   text not null,
  bus_id         int4 references buses(bus_id),
  status         text not null default 'active' check (status in ('active', 'inactive')),
  created_at     timestamptz not null default now()
);

create table if not exists attendance_logs (
  log_id       int8 generated always as identity primary key,
  student_id   int4 not null references students(student_id) on delete cascade,
  bus_id       int4 not null references buses(bus_id),
  action       text not null check (action in ('board', 'exit')),
  location_lat float8,
  location_lng float8,
  "timestamp"  timestamptz not null default now()
);

create table if not exists admins (
  admin_id      int4 generated always as identity primary key,
  email         text not null unique,
  name          text,
  password_hash text not null,
  created_at    timestamptz not null default now()
);

-- ============================================================
-- نظام الباص المدرسي الذكي: تعديلات قاعدة البيانات
-- شغّله مرة واحدة في Supabase: SQL Editor -> New query -> Run
-- (آمن للتكرار: يستخدم IF NOT EXISTS)
-- ============================================================

-- 1) جدول students: حالة الطالب الحالية + رمز ولي الأمر السري
--    نستخدم عمودًا جديدًا current_state ولا نلمس العمود status وقيوده الحالية.
alter table students
  add column if not exists current_state text not null default 'at_home'
    constraint students_current_state_check
    check (current_state in ('at_home', 'on_bus', 'at_school'));

alter table students add column if not exists state_updated_at timestamptz;

-- رمز عشوائي طويل لكل طالب؛ يستخدمه ولي الأمر في الهيدر X-Parent-Token
alter table students
  add column if not exists parent_token text unique not null default gen_random_uuid()::text;

-- 2) جدول buses: السرعة الحالية
alter table buses add column if not exists current_speed float8 default 0;

-- 3) سجل مسار الباص (نقطة لكل إرسال من الـ GPS)
create table if not exists bus_locations (
  location_id bigint generated always as identity primary key,
  bus_id      int4 not null references buses(bus_id) on delete cascade,
  latitude    float8 not null,
  longitude   float8 not null,
  speed       float8 not null default 0,
  recorded_at timestamptz not null default now()
);
create index if not exists bus_locations_bus_time_idx on bus_locations (bus_id, recorded_at desc);

-- 4) طلبات الغياب / عدم استخدام الباص
create table if not exists absence_requests (
  request_id   bigint generated always as identity primary key,
  student_id   int4 not null references students(student_id) on delete cascade,
  request_type text not null check (request_type in ('absent', 'no_bus')),
  start_date   date not null,
  end_date     date not null,
  reason       text,
  status       text not null default 'pending'
               check (status in ('pending', 'approved', 'rejected', 'cancelled')),
  created_at   timestamptz not null default now(),
  check (end_date >= start_date)
);
create index if not exists absence_requests_student_idx on absence_requests (student_id, created_at desc);

-- 5) حماية الجداول الجديدة (السيرفر يستخدم service_role الذي يتجاوز RLS)
alter table bus_locations    enable row level security;
alter table absence_requests enable row level security;

-- ------------------------------------------------------------
-- تحقق مهم: قيود CHECK على attendance_logs (مثل قيد عمود action).
-- السيرفر يكتب action = 'board' أو 'exit'. إن كان لديك قيد بقيم أخرى
-- شغّل هذا الاستعلام وعدّل ACTIONS في config.py لتطابقها:
--
--   select conname, pg_get_constraintdef(oid)
--   from pg_constraint
--   where conrelid = 'attendance_logs'::regclass and contype = 'c';
-- ------------------------------------------------------------
