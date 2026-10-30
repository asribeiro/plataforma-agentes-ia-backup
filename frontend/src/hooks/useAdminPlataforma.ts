/**
 * O usuário logado é o admin master da plataforma?
 *
 * O menu lateral é filtrado por permissão genérica (dashboard, crm, company...),
 * que não conhece "admin da plataforma". Sem isto, o item do painel apareceria
 * para todo mundo e o clique tomaria 403 — a pior versão de uma tela que não
 * funciona: parece bug.
 *
 * `GET /api/admin/eu` responde `admin_plataforma: false` para quem não é (nunca
 * 403, justamente para o menu poder perguntar). O retrato fica em localStorage
 * para o menu já nascer certo no próximo carregamento, sem piscar item proibido.
 */
import { useEffect, useState } from 'react';
import { adminPlataformaApi, type SouAdminPlataforma } from '../services/adminPlataformaApi.ts';
import { CHAVE_ADMIN_PLATAFORMA } from '../services/permissionService.ts';

let cache: SouAdminPlataforma | null = null;
let emAndamento: Promise<SouAdminPlataforma> | null = null;

const guardar = (eu: SouAdminPlataforma) => {
  cache = eu;
  try {
    localStorage.setItem(CHAVE_ADMIN_PLATAFORMA, eu.admin_plataforma ? 'true' : 'false');
  } catch {
    // localStorage bloqueado (modo privado): a tela ainda funciona, só o menu
    // não se antecipa. Não vale derrubar a página por isso.
  }
};

/** Carrega (uma vez por sessão de página) o retrato do admin da plataforma. */
export async function carregarAdminPlataforma(forcar = false): Promise<SouAdminPlataforma> {
  if (cache && !forcar) return cache;
  if (emAndamento && !forcar) return emAndamento;
  emAndamento = adminPlataformaApi
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

export interface EstadoAdminPlataforma {
  ehAdminPlataforma: boolean;
  carregando: boolean;
}

export function useAdminPlataforma(): EstadoAdminPlataforma {
  const [eu, setEu] = useState<SouAdminPlataforma | null>(cache);
  const [carregando, setCarregando] = useState(!cache);

  useEffect(() => {
    let vivo = true;
    setCarregando(!cache);
    carregarAdminPlataforma()
      .then((resultado) => {
        if (!vivo) return;
        setEu(resultado);
      })
      .catch(() => {
        // Falha aqui não é erro de tela: significa apenas "não é admin" para o
        // menu. Quem decide mostrar a tela é o 403 de GET /api/admin/companies.
        if (!vivo) return;
        setEu(null);
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, []);

  return { ehAdminPlataforma: Boolean(eu?.admin_plataforma), carregando };
}
