"""Seed fictício do módulo de prontuário para desenvolvimento local.

Uso:
    set -a && . backend/.env && set +a
    python backend/scripts/seed_prontuario_demo.py

Cria clínicas A/B, profissionais, pacientes, tratamentos, consultas, no-shows,
recorrências e NPS. Não usa dados reais nem envia mensagens externas.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)

CLINICS = [
    {
        "name": "Clínica Demonstração A",
        "cnpj": "99000001000100",
        "professionals": [
            ("Dra. Ana Fictícia", "ana@clinica-a.demo", "CRO-A 1001"),
            ("Dr. Bruno Fictício", "bruno@clinica-a.demo", "CRO-A 1002"),
        ],
    },
    {
        "name": "Clínica Demonstração B",
        "cnpj": "99000002000100",
        "professionals": [
            ("Dra. Clara Fictícia", "clara@clinica-b.demo", "CRO-B 2001"),
            ("Dr. Diego Fictício", "diego@clinica-b.demo", "CRO-B 2002"),
        ],
    },
]

FIRST_NAMES = [
    "Alice", "Beatriz", "Carlos", "Daniel", "Eduarda", "Felipe", "Gabriela", "Henrique",
    "Isabela", "João", "Larissa", "Miguel", "Natália", "Otávio", "Paula",
]
LAST_NAMES = [
    "Fictício", "Exemplo", "Demonstração", "Modelo", "Teste", "Simulado",
]


def ensure_company(conn, name: str, cnpj: str) -> int:
    row = conn.execute(
        text("SELECT id FROM companies WHERE cnpj = :cnpj"),
        {"cnpj": cnpj},
    ).mappings().first()
    if row:
        return int(row["id"])
    row = conn.execute(
        text(
            """
            INSERT INTO companies (name, cnpj, name_company, business_type_id, settings)
            VALUES (:name, :cnpj, :name, 1, '{}'::json)
            RETURNING id
            """
        ),
        {"name": name, "cnpj": cnpj},
    ).mappings().first()
    return int(row["id"])


def ensure_professional(conn, clinic_id: int, name: str, email: str, cro: str) -> int:
    row = conn.execute(
        text(
            """
            INSERT INTO professionals (company_id, name, email, cro)
            VALUES (:clinic_id, :name, :email, :cro)
            ON CONFLICT ON CONSTRAINT uq_professionals_company_email DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        ),
        {"clinic_id": clinic_id, "name": name, "email": email, "cro": cro},
    ).mappings().first()
    return int(row["id"])


def ensure_settings(conn, clinic_id: int):
    conn.execute(
        text(
            """
            INSERT INTO patient_record_module_settings (
                clinic_id, noshow_minutes, recurrence_window_days, survey_delay_hours,
                survey_expiration_hours, inactive_months, google_review_enabled
            )
            VALUES (:clinic_id, 30, 90, 2, 72, 6, false)
            ON CONFLICT (clinic_id) DO NOTHING
            """
        ),
        {"clinic_id": clinic_id},
    )


def seed_clinic(conn, clinic: dict):
    clinic_id = ensure_company(conn, clinic["name"], clinic["cnpj"])
    ensure_settings(conn, clinic_id)
    professional_ids = [
        ensure_professional(conn, clinic_id, name, email, cro)
        for name, email, cro in clinic["professionals"]
    ]

    suffix = "A" if clinic["cnpj"].endswith("0100") else "B"
    now = datetime.now(timezone.utc)
    for index in range(15):
        name = f"{FIRST_NAMES[index]} {LAST_NAMES[index % len(LAST_NAMES)]} {suffix}"
        phone = f"+5511999{suffix == 'A' and '00' or '10'}{100 + index}"
        email = f"paciente.{index + 1}@demo-{suffix.lower()}.test"
        cpf = f"00000{index + 1:03d}{suffix == 'A' and '001' or '002'}"[-11:]
        patient = conn.execute(
            text(
                """
                SELECT id FROM patients
                WHERE clinic_id = :clinic_id AND cpf = :cpf
                """
            ),
            {"clinic_id": clinic_id, "cpf": cpf},
        ).mappings().first()
        if not patient:
            patient = conn.execute(
                text(
                    """
                    INSERT INTO patients (
                        id, clinic_id, name, cpf, birth_date, phone, email, insurance,
                        source, lifecycle_status, lgpd_consent_at, lgpd_consent_version
                    )
                    VALUES (
                        :id, :clinic_id, :name, :cpf, :birth_date, :phone, :email,
                        :insurance, 'seed_demo', 'active', now(), 'demo-lgpd-v1'
                    )
                    RETURNING id
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "clinic_id": clinic_id,
                    "name": name,
                    "cpf": cpf,
                    "birth_date": (now - timedelta(days=365 * (22 + index))).date(),
                    "phone": phone,
                    "email": email,
                    "insurance": "Particular" if index % 3 else "Convênio Demo",
                },
            ).mappings().first()
        patient_id = patient["id"]

        treatment = conn.execute(
            text(
                """
                INSERT INTO treatments (
                    id, clinic_id, patient_id, professional_id, title, description,
                    status, total_value, start_date
                )
                VALUES (
                    :id, :clinic_id, :patient_id, :professional_id, :title,
                    'Tratamento fictício para demonstração', 'in_progress', :total_value, :start_date
                )
                ON CONFLICT DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "clinic_id": clinic_id,
                "patient_id": patient_id,
                "professional_id": professional_ids[index % len(professional_ids)],
                "title": f"Plano preventivo {index + 1}",
                "total_value": Decimal("250.00"),
                "start_date": (now - timedelta(days=90 - index * 3)).date(),
            },
        ).mappings().first()
        if not treatment:
            treatment = conn.execute(
                text(
                    """
                    SELECT id FROM treatments
                    WHERE clinic_id = :clinic_id AND patient_id = :patient_id
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {"id": str(uuid.uuid4()), "clinic_id": clinic_id, "patient_id": patient_id},
            ).mappings().first()
        treatment_id = treatment["id"]

        procedure = conn.execute(
            text(
                """
                INSERT INTO treatment_procedures (
                    id, clinic_id, treatment_id, name, value, status,
                    recurrence_frequency, recurrence_sessions
                )
                VALUES (
                    :id, :clinic_id, :treatment_id, :name, 250.00, 'active', 'monthly', 6
                )
                ON CONFLICT DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "clinic_id": clinic_id,
                "treatment_id": treatment_id,
                "name": f"Acompanhamento mensal {index + 1}",
            },
        ).mappings().first()
        procedure_id = procedure["id"] if procedure else conn.execute(
            text("SELECT id FROM treatment_procedures WHERE treatment_id = :treatment_id LIMIT 1"),
            {"treatment_id": treatment_id},
        ).scalar()

        for session_index in range(3):
            starts_at = now - timedelta(days=70 - session_index * 30 + index)
            status = "no_show" if index % 8 == 0 and session_index == 2 else "attended"
            appointment = conn.execute(
                text(
                    """
                    INSERT INTO patient_appointments (
                        id, clinic_id, patient_id, professional_id, treatment_procedure_id,
                        starts_at, duration_minutes, source, status
                    )
                    VALUES (
                        :id, :clinic_id, :patient_id, :professional_id, :procedure_id,
                        :starts_at, 45, 'seed_demo', :status
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "clinic_id": clinic_id,
                    "patient_id": patient_id,
                    "professional_id": professional_ids[index % len(professional_ids)],
                    "procedure_id": procedure_id,
                    "starts_at": starts_at,
                    "status": status,
                },
            ).mappings().first()
            if not appointment:
                continue
            appointment_id = appointment["id"]
            if status == "attended" and index % 2 == 0:
                nps = 10 if index % 5 else 6
                conn.execute(
                    text(
                        """
                        INSERT INTO satisfaction_surveys (
                            id, clinic_id, appointment_id, patient_id, professional_id,
                            nps_score, procedure_score, comment, channel, status,
                            sent_at, responded_at
                        )
                        VALUES (
                            :id, :clinic_id, :appointment_id, :patient_id, :professional_id,
                            :nps, 5, :comment, 'whatsapp', 'responded', now(), now()
                        )
                        ON CONFLICT ON CONSTRAINT uq_satisfaction_surveys_appointment DO NOTHING
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "clinic_id": clinic_id,
                        "appointment_id": appointment_id,
                        "patient_id": patient_id,
                        "professional_id": professional_ids[index % len(professional_ids)],
                        "nps": nps,
                        "comment": "Atendimento fictício excelente" if nps >= 9 else "Atendimento fictício abaixo do esperado",
                    },
                )

        conn.execute(
            text(
                """
                INSERT INTO patient_timeline_events (
                    id, clinic_id, patient_id, event_type, payload
                )
                VALUES (
                    :id, :clinic_id, :patient_id, 'seed_demo_created',
                    '{"seed": true}'::jsonb
                )
                """
            ),
            {"id": str(uuid.uuid4()), "clinic_id": clinic_id, "patient_id": patient_id},
        )

    return clinic_id


def main():
    with engine.begin() as conn:
        clinic_ids = [seed_clinic(conn, clinic) for clinic in CLINICS]
        counts = conn.execute(
            text(
                """
                SELECT clinic_id, count(*) AS patients
                FROM patients
                WHERE clinic_id = ANY(:clinic_ids)
                GROUP BY clinic_id
                ORDER BY clinic_id
                """
            ),
            {"clinic_ids": clinic_ids},
        ).mappings().all()
        print("Seed de prontuário concluído:")
        for row in counts:
            print(f"  clínica {row['clinic_id']}: {row['patients']} pacientes")


if __name__ == "__main__":
    main()
