import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import { ThemeProvider } from '../contexts/ThemeContext';
import PatientRecordPage from './PatientRecordPage';
import { patientRecordApi } from '../services/patientRecordApi';

describe('PatientRecordPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(patientRecordApi, 'listPatients').mockResolvedValue([]);
  });

  it('submits a valid patient payload with masked formatting and normalized values', async () => {
    const createPatientSpy = vi.spyOn(patientRecordApi, 'createPatient').mockResolvedValue({
      id: 'patient-1',
      name: 'Ana Maria da Silva',
      cpf: '34450197976',
      birth_date: '1990-05-21',
      phone: '11987654321',
      email: 'ana.silva@example.com',
      insurance: 'Particular',
      lifecycle_status: 'lead',
      last_appointment_at: null,
      next_appointment_at: null,
      no_show_count: 0,
      total_appointments: 0,
    });

    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={['/prontuario/pacientes']}>
          <Routes>
            <Route path="/prontuario/pacientes" element={<PatientRecordPage />} />
            <Route path="/prontuario/pacientes/:patientId" element={<PatientRecordPage />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    fireEvent.click(screen.getAllByRole('button', { name: /novo paciente/i })[0]);

    const nameInput = screen.getByLabelText(/nome completo/i);
    const cpfInput = screen.getByLabelText(/cpf/i);
    const birthInput = screen.getByLabelText(/data de nascimento/i);
    const phoneInput = screen.getByLabelText(/telefone\/whatsapp/i);
    const emailInput = screen.getByLabelText(/e-mail/i);
    const insuranceInput = screen.getByLabelText(/convênio/i);
    const sourceInput = screen.getByLabelText(/origem/i);

    fireEvent.change(nameInput, { target: { value: 'Ana Maria da Silva' } });
    fireEvent.change(cpfInput, { target: { value: '34450197976' } });
    fireEvent.change(birthInput, { target: { value: '1990-05-21' } });
    fireEvent.change(phoneInput, { target: { value: '11987654321' } });
    fireEvent.change(emailInput, { target: { value: 'Ana.Silva@EXAMPLE.com  ' } });
    fireEvent.change(insuranceInput, { target: { value: 'Particular' } });
    fireEvent.change(sourceInput, { target: { value: 'Landing page' } });

    await waitFor(() => {
      expect(cpfInput).toHaveValue('344.501.979-76');
      expect(phoneInput).toHaveValue('(11) 98765-4321');
      expect(emailInput).toHaveValue('ana.silva@example.com');
    });

    fireEvent.click(screen.getByRole('button', { name: /criar paciente/i }));

    await waitFor(() => {
      expect(createPatientSpy).toHaveBeenCalledWith({
        name: 'Ana Maria da Silva',
        cpf: '34450197976',
        birth_date: '1990-05-21',
        phone: '11987654321',
        email: 'ana.silva@example.com',
        insurance: 'Particular',
        source: 'Landing page',
      });
    });
  });
});
