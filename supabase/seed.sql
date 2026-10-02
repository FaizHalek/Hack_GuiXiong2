-- Demo labels (one per company research library). Promote your first user to
-- admin after signing up:
--   update public.profiles set role = 'admin' where email = 'you@example.com';

insert into public.labels (name, description, color) values
  ('Acme Corp',   'Acme Corp research library',   '#2563eb'),
  ('Globex',      'Globex research library',      '#16a34a'),
  ('Initech',     'Initech research library',     '#d97706')
on conflict (name) do nothing;
