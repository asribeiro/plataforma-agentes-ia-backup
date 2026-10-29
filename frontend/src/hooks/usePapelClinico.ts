/**
 * Papel clínico do usuário logado, para a TELA se esconder quando não pode.
 *
 * O menu lateral hoje é filtrado por "permissão de equipe" (dashboard, crm,
 * company...), que não conhece papel clínico. Sem isso, um Profissional de
 * Atendimento veria "Equipe" no menu, clicaria e tomaria 403 — a pior versão de
 * uma tela que não funciona: parece bug.
 *
 * O retrato vem de GET /api/clinic/users/eu (qualquer papel logado pode ler o
 * próprio). Guardamos o resultado em localStorage para o menu já nascer certo no
 * próximo carregamento, sem piscar item proibido.
 */
import { useEffect, useState } from 'react';
import { equipeApi, type EuClinica } from '../services/clinicUsersApi.ts';

export const CHAVE_PODE_ADMINISTRAR = 'clinic_pode_administrar_usuarios';
export const CHAVE_VE_PRONTUARIO = 'clinic_ve_prontuario';
export const CHAVE_PAPEL = 'clinic_role';

let cache: EuClinica | null = null;
let emAndamento: Promise<EuClinica> | null = null;

const guardar = (eu: EuClinica) => {
  cache = eu;
  try {
    localStorage.setItem(CHAVE_PODE_ADMINISTRAR, eu.pode_administrar_usuarios ? 'true' : 'false');
    localStorage.setItem(CHAVE_VE_PRONTUARIO, eu.ve_prontuario ? 'true' : 'false');
    localStorage.setItem(CHAVE_PAPEL, eu.role || '');
  } catch {
    // localStorage bloqueado (modo privado): a tela ainda funciona, só o menu
    // não se antecipa. Não vale derrubar a página por isso.
  }
};

/** Carrega (uma vez por sessão de página) o retrato do usuário logado. */
export async function carregarPapelClinico(forcar = false): Promise<EuClinica> {
  if (cache && !forcar) return cache;
  if (emAndamento && !forcar) return emAndamento;
  emAndamento = equipeApi
    .eu()
    .then((eu) => {
      guardar(eu);
      return eu;
    })
    .finally(() => {
      emAndamento = null;
    });
  return emAndamento;
}

export interface EstadoPapelClinico {
  eu: EuClinica | null;
  carregando: boolean;
  erro: string | null;
  recarregar: () => void;
}

export function usePapelClinico(): EstadoPapelClinico {
  const [eu, setEu] = useState<EuClinica | null>(cache);
  const [carregando, setCarregando] = useState(!cache);
  const [erro, setErro] = useState<string | null>(null);
  const [gatilho, setGatilho] = useState(0);

  useEffect(() => {
    let vivo = true;
    setCarregando(!cache);
    carregarPapelClinico(gatilho > 0)
      .then((resultado) => {
        if (!vivo) return;
        setEu(resultado);
        setErro(null);
      })
      .catch(() => {
        if (!vivo) return;
        setErro('Não foi possível identificar seu papel nesta clínica.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [gatilho]);

  return { eu, carregando, erro, recarregar: () => setGatilho((n) => n + 1) };
}
