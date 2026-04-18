-- seeds/mock_data.sql
INSERT INTO tenants (
  id, slug, name, hr_email, telegram_bot_token, telegram_webhook_secret, settings_json
) VALUES (
  '11111111-1111-1111-1111-111111111111',
  'acme',
  'ACME Recruiting',
  'rrhh@acme.test',
  '5893294067:AAGXqXwLF1njIftX9O_HD8hNpuCMnrchbLg',
  'telegram-secret-acme',
  '{"brand":"ACME","notify_top_n":5}'::jsonb
);

INSERT INTO vacancies (
  id, tenant_id, code, title, description, responsibilities,
  mandatory_requirements, desirable_requirements,
  salary_text, schedule_text, location_text, benefits,
  faq_context, cv_score_factor, classification_thresholds, status
) VALUES (
  '22222222-2222-2222-2222-222222222222',
  '11111111-1111-1111-1111-111111111111',
  'BE-PY-001',
  'Backend Python FastAPI',
  'Desarrollo y mantenimiento de APIs REST multi-tenant para producto SaaS.',
  ARRAY['Construir endpoints', 'Mantener PostgreSQL', 'Integrar bots'],
  ARRAY['2+ años con FastAPI', '2+ años con PostgreSQL', 'Permiso de trabajo'],
  ARRAY['Docker', 'Render', 'Telegram Bot API'],
  '40k-55k EUR',
  'L-V 09:00-18:00',
  'Madrid híbrido',
  ARRAY['Seguro médico', 'Formación', 'Horario flexible'],
  '{
    "items": [
      {"question":"¿Es remoto?", "answer":"Es híbrido, con 2-3 días presenciales.", "keywords":["remoto","hibrido","presencial"]},
      {"question":"¿Cuál es el horario?", "answer":"Horario base de lunes a viernes de 09:00 a 18:00.", "keywords":["horario","turno"]},
      {"question":"¿Cuál es el salario?", "answer":"La banda objetivo es 40k-55k EUR.", "keywords":["salario","sueldo","pago"]}
    ]
  }'::jsonb,
  6.00,
  '{"review":35,"interview":60,"shortlist":75}'::jsonb,
  'active'
);

INSERT INTO questions (id, tenant_id, code, prompt_text, answer_type, default_validation) VALUES
('30000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'work_permit', '¿Tienes permiso de trabajo vigente?', 'boolean', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'years_fastapi', '¿Cuántos años de experiencia tienes con FastAPI?', 'number', '{"min":0,"max":50}'::jsonb),
('30000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'years_postgres', '¿Cuántos años de experiencia tienes con PostgreSQL?', 'number', '{"min":0,"max":50}'::jsonb),
('30000000-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', 'english_level', '¿Cuál es tu nivel de inglés?', 'text', '{"min_len":1,"max_len":20}'::jsonb),
('30000000-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', 'oncall_available', '¿Puedes entrar en guardias puntuales?', 'boolean', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb);

INSERT INTO vacancy_questions (
  id, tenant_id, vacancy_id, question_id, question_order, field_key, validation, required, scoring_enabled
) VALUES
('40000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000001', 1, 'work_permit', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000002', 2, 'years_fastapi', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000003', 3, 'years_postgres', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000004', 4, 'english_level', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000005', 5, 'oncall_available', '{}'::jsonb, true, true);

INSERT INTO scoring_rules (
  id, tenant_id, vacancy_id, name, source_scope, field_key, operator,
  expected_text, expected_number, expected_boolean, points, is_disqualifier, priority
) VALUES
('50000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'Sin permiso de trabajo', 'answer', 'work_permit', 'equals', NULL, NULL, false, 0, true, 1),
('50000000-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'FastAPI 2+ años', 'answer', 'years_fastapi', 'gte', NULL, 2, NULL, 8, false, 10),
('50000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'PostgreSQL 2+ años', 'answer', 'years_postgres', 'gte', NULL, 2, NULL, 6, false, 20),
('50000000-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'Inglés B2', 'answer', 'english_level', 'contains', 'b2', NULL, NULL, 3, false, 30),
('50000000-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'Disponible para guardias', 'answer', 'oncall_available', 'equals', NULL, NULL, true, 2, false, 40);
