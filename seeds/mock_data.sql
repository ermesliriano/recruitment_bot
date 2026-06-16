-- seeds/mock_data.sql
truncate table tenant_questions, tenants, vacancies, questions, vacancy_questions, candidates, applications, answers, cv_documents, ai_evaluations, conversation_sessions, scoring_rules, system_logs, outbound_messages, cv_import_jobs, cv_import_job_items;
truncate table cv_import_job_items, outbound_messages, candidates, applications, answers, cv_documents, ai_evaluations, conversation_sessions, system_logs;
 
INSERT INTO tenants (
  id, slug, name, hr_email, telegram_bot_token, telegram_webhook_secret, settings_json, is_active, whatsapp_enabled, whatsapp_use_env_credentials, whatsapp_messaging_service_sid, whatsapp_sender_address, whatsapp_initial_template_sid, whatsapp_initial_template_language, whatsapp_assume_opt_in
) VALUES (
  '11111111-1111-1111-1111-111111111111',
  'cesaria',
  'Cesaria HR',
  'rrhh@cesaria.test',
  '8789717115:AAGMh8fDoEvB6tDW6R_b5nYCRqADF6PnNFM',
  'telegram-secret-cesaria',
  '{"brand":"Cesaria","notify_top_n":5}'::jsonb,
  TRUE,
  TRUE,
  TRUE,
  'MG58bf7a67487a7240785f173109e55996',
  'whatsapp:+18492680377',
  'HX46e91532d66b1f82a4923af6bdb83ace',
  'es',
  TRUE
  );

INSERT INTO vacancies (
  id, tenant_id, code, title, description, responsibilities,
  mandatory_requirements, desirable_requirements,
  salary_text, schedule_text, location_text, benefits,
  faq_context, cv_max_score, classification_thresholds, status
) VALUES (
  '22222222-2222-2222-2222-222222222303',
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
  40,
  '{"review":35,"interview":60,"shortlist":75}'::jsonb,
  'ACTIVE'
);

INSERT INTO questions (id, tenant_id, code, prompt_text, answer_type, default_validation) VALUES
('30000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'work_permit', '¿Tienes permiso de trabajo vigente?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'years_fastapi', '¿Cuántos años de experiencia tienes con FastAPI?', 'NUMBER', '{"min":0,"max":50}'::jsonb),
('30000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'years_postgres', '¿Cuántos años de experiencia tienes con PostgreSQL?', 'NUMBER', '{"min":0,"max":50}'::jsonb),
('30000000-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', 'english_level', '¿Cuál es tu nivel de inglés?', 'TEXT', '{"min_len":1,"max_len":20}'::jsonb),
('30000000-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', 'oncall_available', '¿Puedes entrar en guardias puntuales?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb);

INSERT INTO vacancy_questions (
  id, tenant_id, vacancy_id, question_id, question_order, field_key, validation, required, scoring_enabled, max_points
) VALUES
('40000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000001', 1, 'work_permit', '{}'::jsonb, true, true, 0),
('40000000-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000002', 2, 'years_fastapi', '{}'::jsonb, true, true, 25),
('40000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000003', 3, 'years_postgres', '{}'::jsonb, true, true, 20),
('40000000-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000004', 4, 'english_level', '{}'::jsonb, true, true, 10),
('40000000-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', '30000000-0000-0000-0000-000000000005', 5, 'oncall_available', '{}'::jsonb, true, true, 5);

INSERT INTO scoring_rules (
  id, tenant_id, vacancy_id, name, source_scope, field_key, operator,
  expected_text, expected_number, expected_boolean, points, is_disqualifier, priority
) VALUES
('50000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'Sin permiso de trabajo', 'ANSWER', 'work_permit', 'EQUALS', NULL, NULL, false, 0, true, 1),
('50000000-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'FastAPI 2+ años', 'ANSWER', 'years_fastapi', 'GTE', NULL, 2, NULL, 25, false, 10),
('50000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'PostgreSQL 2+ años', 'ANSWER', 'years_postgres', 'GTE', NULL, 2, NULL, 20, false, 20),
('50000000-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'Inglés B2', 'ANSWER', 'english_level', 'CONTAINS', 'b2', NULL, NULL, 10, false, 30),
('50000000-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'Disponible para guardias', 'ANSWER', 'oncall_available', 'EQUALS', NULL, NULL, true, 5, false, 40);

/* =========================================================
   VACANTE 1: ANALISTA SENIOR DE IMPUESTOS
   Empresa: Termo Envases
   ========================================================= */

INSERT INTO vacancies (
  id, tenant_id, code, title, description, responsibilities,
  mandatory_requirements, desirable_requirements,
  salary_text, schedule_text, location_text, benefits,
  faq_context, cv_score_factor, classification_thresholds, status
) VALUES (
  '22222222-2222-2222-2222-222222222301',
  '11111111-1111-1111-1111-111111111111',
  'TE-IMP-001',
  'Analista Senior de Impuestos',
  'Vacante para Analista Senior de Impuestos en Termo Envases, orientada a garantizar el cumplimiento oportuno y correcto de las obligaciones fiscales, contables y financieras de la empresa.',
  ARRAY[
    'Garantizar el cumplimiento oportuno y correcto de las obligaciones fiscales',
    'Asegurar la presentación, registro y pago de impuestos, retenciones y cuentas por pagar',
    'Controlar procesos relacionados con proveedores, bancos y normativas impositivas',
    'Gestionar procesos administrativos como caja chica, reembolsos, proveedores, reclamos a bancos y DGII'
  ],
  ARRAY[
    'Licenciatura en Contabilidad o carreras afines',
    '2 o más años de experiencia sólida en impuestos y contabilidad',
    'Dominio de impuestos locales: ITBIS, TSS, IR-3, IR-17, anticipos, Infotep, aduanas y NCF',
    'Manejo de cuentas por pagar, retenciones, facturación y conciliaciones contables',
    'Dominio de plataformas bancarias para pagos locales e internacionales',
    'Experiencia en sistemas contables y control de secuencias fiscales',
    'Microsoft Office y Excel avanzado'
  ],
  ARRAY[
    'Experiencia en industria de manufactura, preferiblemente plásticos',
    'Capacidad de análisis y organización',
    'Orientación a resultados con calidad y mejora continua',
    'Proactividad',
    'Buena comunicación oral y escrita'
  ],
  'No especificado',
  'No especificado',
  'No especificado',
  ARRAY[
    'Oportunidad laboral en Termo Envases',
    'Entorno orientado a resultados y mejora continua'
  ],
  '{
    "items": [
      {
        "question": "¿Cuál es el propósito del cargo?",
        "answer": "Garantizar el cumplimiento oportuno y correcto de las obligaciones fiscales, contables y financieras de la empresa, asegurando la presentación, registro y pago de impuestos, retenciones y cuentas por pagar.",
        "keywords": ["proposito", "cargo", "funciones", "impuestos", "contabilidad"]
      },
      {
        "question": "¿Qué formación académica se requiere?",
        "answer": "Se requiere Licenciatura en Contabilidad o carreras afines.",
        "keywords": ["formacion", "licenciatura", "contabilidad", "carreras afines"]
      },
      {
        "question": "¿Cuánta experiencia se requiere?",
        "answer": "Se requieren 2 o más años de experiencia sólida en impuestos y contabilidad, idealmente en industria de manufactura.",
        "keywords": ["experiencia", "años", "manufactura", "impuestos"]
      },
      {
        "question": "¿Cómo puedo aplicar?",
        "answer": "Debes enviar tu CV al correo Talentos@termoenvases.com.do.",
        "keywords": ["aplicar", "cv", "correo", "talentos"]
      }
    ]
  }'::jsonb,
  6.00,
  '{"review":35,"interview":60,"shortlist":75}'::jsonb,
  'ACTIVE'
);


/* =========================================================
   VACANTE 2: PLANIFICADOR/A DE PRODUCCIÓN
   Empresa: Termo Envases
   ========================================================= */

INSERT INTO vacancies (
  id, tenant_id, code, title, description, responsibilities,
  mandatory_requirements, desirable_requirements,
  salary_text, schedule_text, location_text, benefits,
  faq_context, cv_score_factor, classification_thresholds, status
) VALUES (
  '22222222-2222-2222-2222-222222222302',
  '11111111-1111-1111-1111-111111111111',
  'TE-PLAN-001',
  'Planificador/a de Producción',
  'Vacante para Planificador/a de Producción en Termo Envases, enfocada en coordinar y realizar la planificación de las áreas de producción y actividades de apoyo operativo.',
  ARRAY[
    'Coordinar y realizar la planificación de las áreas de producción',
    'Planificar actividades de apoyo operativo necesarias para el cumplimiento de la producción',
    'Gestionar disponibilidad de materiales y mano de obra',
    'Dar seguimiento a tiempos de producción',
    'Controlar cambios relacionados con la planificación productiva'
  ],
  ARRAY[
    'Grado académico de Ingeniería Industrial u otra ingeniería relacionada con manejo de procesos de planificación',
    'Excel avanzado indispensable',
    'Técnicas de Gestión de Producción y/o Manufactura Esbelta',
    'Mínimo 2 años de experiencia en coordinación operativa de la gestión de planificación de la producción'
  ],
  ARRAY[
    'Autodirección',
    'Pensamiento analítico',
    'Orientación a resultados con calidad y mejora continua',
    'Comunicación eficaz e influencia',
    'Negociación'
  ],
  'No especificado',
  'No especificado',
  'No especificado',
  ARRAY[
    'Oportunidad laboral en Termo Envases',
    'Entorno de producción y mejora continua'
  ],
  '{
    "items": [
      {
        "question": "¿Cuál es el propósito del cargo?",
        "answer": "Coordinar y realizar la planificación de las áreas de producción y las actividades de apoyo operativo necesarias, incluyendo disponibilidad de materiales, mano de obra, seguimiento de tiempos y control de cambios.",
        "keywords": ["proposito", "cargo", "produccion", "planificacion", "materiales"]
      },
      {
        "question": "¿Qué formación académica se requiere?",
        "answer": "Se requiere grado académico de Ingeniería Industrial u otra ingeniería relacionada con manejo de procesos de planificación.",
        "keywords": ["formacion", "ingenieria industrial", "planificacion"]
      },
      {
        "question": "¿Excel avanzado es obligatorio?",
        "answer": "Sí, el Excel avanzado aparece como requisito indispensable para el cargo.",
        "keywords": ["excel", "avanzado", "indispensable"]
      },
      {
        "question": "¿Cómo puedo aplicar?",
        "answer": "Debes enviar tu CV al correo Talentos@termoenvases.com.do.",
        "keywords": ["aplicar", "cv", "correo", "talentos"]
      }
    ]
  }'::jsonb,
  6.00,
  '{"review":35,"interview":60,"shortlist":75}'::jsonb,
  'ACTIVE'
);


/* =========================================================
   VACANTE 3: COORDINADOR/A DE PRODUCCIÓN
   Empresa: Cooperativa - Sector Productivo
   Ubicación: Salcedo, Provincia Hermanas Mirabal
   ========================================================= */

INSERT INTO vacancies (
  id, tenant_id, code, title, description, responsibilities,
  mandatory_requirements, desirable_requirements,
  salary_text, schedule_text, location_text, benefits,
  faq_context, cv_max_score, classification_thresholds, status
) VALUES (
  '22222222-2222-2222-2222-222222222303',
  '11111111-1111-1111-1111-111111111111',
  'COOP-PROD-001',
  'Coordinador/a de Producción',
  'Vacante para Coordinador/a de Producción en una cooperativa del sector productivo, ubicada en Salcedo, Provincia Hermanas Mirabal.',
  ARRAY[
    'Coordinar, supervisar y optimizar las operaciones de producción',
    'Garantizar el cumplimiento de los planes establecidos',
    'Asegurar la calidad del producto',
    'Promover el uso eficiente de los recursos',
    'Liderar equipos operativos alineados con los principios y objetivos de la cooperativa'
  ],
  ARRAY[
    'Formación académica en Ingeniería Industrial, Ingeniería en Agronomía o carreras afines',
    'Mínimo 3 años en roles similares de producción, operaciones o supervisión',
    'Experiencia liderando equipos operativos'
  ],
  ARRAY[
    'Experiencia en cooperativas o sector agroindustrial',
    'Capacidad de coordinación y supervisión',
    'Orientación a calidad y eficiencia de recursos'
  ],
  'No especificado',
  'No especificado',
  'Salcedo, Provincia Hermanas Mirabal',
  ARRAY[
    'Oportunidad de crecimiento en cooperativa',
    'Contribución al desarrollo sostenible del sector productivo'
  ],
  '{
    "items": [
      {
        "question": "¿Cuál es el propósito del puesto?",
        "answer": "Coordinar, supervisar y optimizar las operaciones de producción, garantizando el cumplimiento de los planes establecidos, la calidad del producto y el uso eficiente de los recursos.",
        "keywords": ["proposito", "puesto", "produccion", "supervision", "calidad"]
      },
      {
        "question": "¿Dónde está ubicada la vacante?",
        "answer": "La vacante está ubicada en Salcedo, Provincia Hermanas Mirabal.",
        "keywords": ["ubicacion", "salcedo", "hermanas mirabal"]
      },
      {
        "question": "¿Qué formación académica se requiere?",
        "answer": "Se requiere Ingeniería Industrial, Ingeniería en Agronomía o carreras afines.",
        "keywords": ["formacion", "ingenieria industrial", "agronomia"]
      },
      {
        "question": "¿Cómo puedo aplicar?",
        "answer": "Los interesados deben enviar su CV vía WhatsApp al 809-604-5463, colocando en el asunto: Coordinador(a) de Producción – Salcedo.",
        "keywords": ["aplicar", "cv", "whatsapp", "809-604-5463", "salcedo"]
      }
    ]
  }'::jsonb,
  40,
  '{"review":35,"interview":60,"shortlist":75}'::jsonb,
  'DRAFT'
);


/* =========================================================
   QUESTIONS
   ========================================================= */

INSERT INTO questions (id, tenant_id, code, prompt_text, answer_type, default_validation) VALUES

/* Analista Senior de Impuestos */
('30000000-0000-0000-0000-000000000301', '11111111-1111-1111-1111-111111111111', 'tax_degree_accounting', '¿Tienes Licenciatura en Contabilidad o una carrera afín?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000302', '11111111-1111-1111-1111-111111111111', 'tax_years_experience', '¿Cuántos años de experiencia tienes en impuestos y contabilidad?', 'NUMBER', '{"min":0,"max":50}'::jsonb),
('30000000-0000-0000-0000-000000000303', '11111111-1111-1111-1111-111111111111', 'tax_local_taxes_knowledge', '¿Dominas impuestos locales como ITBIS, TSS, IR-3, IR-17, anticipos, Infotep, aduanas y NCF?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000304', '11111111-1111-1111-1111-111111111111', 'tax_accounts_payable_experience', '¿Tienes experiencia en cuentas por pagar, retenciones, facturación y conciliaciones contables?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000305', '11111111-1111-1111-1111-111111111111', 'tax_excel_advanced', '¿Tienes manejo avanzado de Microsoft Office y Excel?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),

/* Planificador/a de Producción */
('30000000-0000-0000-0000-000000000306', '11111111-1111-1111-1111-111111111111', 'planner_engineering_degree', '¿Tienes grado académico en Ingeniería Industrial u otra ingeniería relacionada con procesos de planificación?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000307', '11111111-1111-1111-1111-111111111111', 'planner_excel_advanced', '¿Tienes Excel avanzado?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000308', '11111111-1111-1111-1111-111111111111', 'planner_lean_production', '¿Tienes conocimientos en Gestión de Producción y/o Manufactura Esbelta?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000309', '11111111-1111-1111-1111-111111111111', 'planner_years_experience', '¿Cuántos años de experiencia tienes en coordinación operativa de planificación de la producción?', 'NUMBER', '{"min":0,"max":50}'::jsonb),
('30000000-0000-0000-0000-000000000310', '11111111-1111-1111-1111-111111111111', 'planner_negotiation_skills', '¿Tienes experiencia o fortaleza en comunicación, influencia y negociación?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),

/* Coordinador/a de Producción */
('30000000-0000-0000-0000-000000000311', '11111111-1111-1111-1111-111111111111', 'coord_engineering_degree', '¿Tienes formación en Ingeniería Industrial, Ingeniería en Agronomía o una carrera afín?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000312', '11111111-1111-1111-1111-111111111111', 'coord_years_experience', '¿Cuántos años de experiencia tienes en roles similares de producción, operaciones o supervisión?', 'NUMBER', '{"min":0,"max":50}'::jsonb),
('30000000-0000-0000-0000-000000000313', '11111111-1111-1111-1111-111111111111', 'coord_cooperative_agro_experience', '¿Tienes experiencia en cooperativas o en el sector agroindustrial?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000314', '11111111-1111-1111-1111-111111111111', 'coord_team_leadership', '¿Tienes experiencia liderando equipos operativos?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb),
('30000000-0000-0000-0000-000000000315', '11111111-1111-1111-1111-111111111111', 'coord_salcedo_available', '¿Tienes disponibilidad para trabajar en Salcedo, Provincia Hermanas Mirabal?', 'BOOLEAN', '{"true_values":["si","sí"],"false_values":["no"]}'::jsonb);


/* =========================================================
   VACANCY QUESTIONS
   ========================================================= */

INSERT INTO vacancy_questions (
  id, tenant_id, vacancy_id, question_id, question_order, field_key, validation, required, scoring_enabled
) VALUES

/* Analista Senior de Impuestos */
('40000000-0000-0000-0000-000000000301', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', '30000000-0000-0000-0000-000000000301', 1, 'tax_degree_accounting', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000302', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', '30000000-0000-0000-0000-000000000302', 2, 'tax_years_experience', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000303', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', '30000000-0000-0000-0000-000000000303', 3, 'tax_local_taxes_knowledge', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000304', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', '30000000-0000-0000-0000-000000000304', 4, 'tax_accounts_payable_experience', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000305', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', '30000000-0000-0000-0000-000000000305', 5, 'tax_excel_advanced', '{}'::jsonb, true, true),

/* Planificador/a de Producción */
('40000000-0000-0000-0000-000000000306', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', '30000000-0000-0000-0000-000000000306', 1, 'planner_engineering_degree', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000307', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', '30000000-0000-0000-0000-000000000307', 2, 'planner_excel_advanced', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000308', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', '30000000-0000-0000-0000-000000000308', 3, 'planner_lean_production', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000309', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', '30000000-0000-0000-0000-000000000309', 4, 'planner_years_experience', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000310', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', '30000000-0000-0000-0000-000000000310', 5, 'planner_negotiation_skills', '{}'::jsonb, true, true),

/* Coordinador/a de Producción */
('40000000-0000-0000-0000-000000000311', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', '30000000-0000-0000-0000-000000000311', 1, 'coord_engineering_degree', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000312', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', '30000000-0000-0000-0000-000000000312', 2, 'coord_years_experience', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000313', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', '30000000-0000-0000-0000-000000000313', 3, 'coord_cooperative_agro_experience', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000314', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', '30000000-0000-0000-0000-000000000314', 4, 'coord_team_leadership', '{}'::jsonb, true, true),
('40000000-0000-0000-0000-000000000315', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', '30000000-0000-0000-0000-000000000315', 5, 'coord_salcedo_available', '{}'::jsonb, true, true);


/* =========================================================
   SCORING RULES
   ========================================================= */

INSERT INTO scoring_rules (
  id, tenant_id, vacancy_id, name, source_scope, field_key, operator,
  expected_text, expected_number, expected_boolean, points, is_disqualifier, priority
) VALUES

/* Analista Senior de Impuestos */
('50000000-0000-0000-0000-000000000301', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', 'Sin formación en Contabilidad o carrera afín', 'ANSWER', 'tax_degree_accounting', 'EQUALS', NULL, NULL, false, 0, true, 1),
('50000000-0000-0000-0000-000000000302', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', 'Experiencia en impuestos y contabilidad 2+ años', 'ANSWER', 'tax_years_experience', 'GTE', NULL, 2, NULL, 8, false, 10),
('50000000-0000-0000-0000-000000000303', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', 'Dominio de impuestos locales', 'ANSWER', 'tax_local_taxes_knowledge', 'EQUALS', NULL, NULL, true, 8, false, 20),
('50000000-0000-0000-0000-000000000304', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', 'Experiencia en cuentas por pagar y conciliaciones', 'ANSWER', 'tax_accounts_payable_experience', 'EQUALS', NULL, NULL, true, 6, false, 30),
('50000000-0000-0000-0000-000000000305', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222301', 'Excel avanzado', 'ANSWER', 'tax_excel_advanced', 'EQUALS', NULL, NULL, true, 5, false, 40),

/* Planificador/a de Producción */
('50000000-0000-0000-0000-000000000306', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', 'Sin formación en ingeniería relacionada', 'ANSWER', 'planner_engineering_degree', 'EQUALS', NULL, NULL, false, 0, true, 1),
('50000000-0000-0000-0000-000000000307', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', 'Excel avanzado indispensable', 'ANSWER', 'planner_excel_advanced', 'EQUALS', NULL, NULL, true, 8, false, 10),
('50000000-0000-0000-0000-000000000308', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', 'Gestión de Producción o Manufactura Esbelta', 'ANSWER', 'planner_lean_production', 'EQUALS', NULL, NULL, true, 6, false, 20),
('50000000-0000-0000-0000-000000000309', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', 'Experiencia en planificación de producción 2+ años', 'ANSWER', 'planner_years_experience', 'GTE', NULL, 2, NULL, 8, false, 30),
('50000000-0000-0000-0000-000000000310', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222302', 'Comunicación, influencia y negociación', 'ANSWER', 'planner_negotiation_skills', 'EQUALS', NULL, NULL, true, 3, false, 40),

/* Coordinador/a de Producción */
('50000000-0000-0000-0000-000000000311', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', 'Sin formación en Ingeniería Industrial, Agronomía o afín', 'ANSWER', 'coord_engineering_degree', 'EQUALS', NULL, NULL, false, 0, true, 1),
('50000000-0000-0000-0000-000000000312', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', 'Experiencia en producción, operaciones o supervisión 3+ años', 'ANSWER', 'coord_years_experience', 'GTE', NULL, 3, NULL, 9, false, 10),
('50000000-0000-0000-0000-000000000313', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', 'Experiencia en cooperativas o sector agroindustrial', 'ANSWER', 'coord_cooperative_agro_experience', 'EQUALS', NULL, NULL, true, 6, false, 20),
('50000000-0000-0000-0000-000000000314', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', 'Liderazgo de equipos operativos', 'ANSWER', 'coord_team_leadership', 'EQUALS', NULL, NULL, true, 7, false, 30),
('50000000-0000-0000-0000-000000000315', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222303', 'Disponibilidad para trabajar en Salcedo', 'ANSWER', 'coord_salcedo_available', 'EQUALS', NULL, NULL, true, 5, false, 40);