import { LucideIcon } from 'lucide-react';

// Tipos para permissões
export type UserRole = string;
export type UserType = 'user' | 'master';
export type Permission =
  | 'dashboard'
  | 'crm'
  | 'chat'
  | 'whatsapp'
  | 'follow-up'
  | 'prompt'
  | 'company';

// Interface para MenuItem (compatível com ProtectedLayout)
export interface MenuItem {
  path: string;
  icon: LucideIcon;
  label: string;
  badge?: string;
  status?: string;
  subItems?: SubItem[];
  permission?: Permission; // Nova propriedade para controle de acesso
  isNew?: boolean;
  isBeta?: boolean;
  isGroup?: boolean;
  /** So aparece para quem administra usuarios da clinica (papel clinico). */
  requiresClinicalAdmin?: boolean;
  /** So aparece para o admin master da plataforma (flag de useAdminPlataforma). */
  requiresPlatformAdmin?: boolean;
}

export interface SubItem {
  path: string;
  label: string;
  icon?: LucideIcon;
  isNew?: boolean;
  isBeta?: boolean;
  permission?: Permission; // Nova propriedade para controle de acesso
  subItems?: SubItem[]; // Suporte a n-níveis (L3)
  /** Idem: escondido de quem nao administra a equipe da clinica. */
  requiresClinicalAdmin?: boolean;
  /** Idem: escondido de quem nao e admin master da plataforma. */
  requiresPlatformAdmin?: boolean;
}

export const USER_TYPE_PERMISSIONS: Record<UserType, Permission[]> = {
  user: [],
  master: ['dashboard', 'crm', 'chat', 'whatsapp', 'follow-up', 'prompt', 'company']
};

const parseStoredPermissions = (): Permission[] | null => {
  const raw = localStorage.getItem('sidebar_permissions');
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    const allowed = new Set<Permission>(['dashboard', 'crm', 'chat', 'whatsapp', 'follow-up', 'prompt', 'company']);
    return parsed
      .map((item) => item === 'clinic' ? 'company' : item)
      .filter((item): item is Permission => allowed.has(item));
  } catch (error) {
    console.error('Erro ao parsear sidebar_permissions:', error);
    return null;
  }
};

/**
 * Obtém o role do usuário a partir do localStorage
 */
export const getUserRole = (): UserRole | null => {
  // Primeiro verifica se é master
  const userType = localStorage.getItem('user_type');
  if (userType === 'master') {
    return 'MASTER';
  }

  const userTeamData = localStorage.getItem('user_team_data');
  if (userTeamData) {
    try {
      const team = JSON.parse(userTeamData);
      const label = String(team?.name || team?.code || '').trim();
      return label || null;
    } catch (error) {
      console.error('Erro ao parsear user_team_data:', error);
    }
  }

  const userTeam = localStorage.getItem('user_team');
  if (userTeam) {
    return userTeam;
  }

  return null;
};

/**
 * Obtém o tipo do usuário a partir do localStorage
 */
export const getUserType = (): UserType => {
  const userType = localStorage.getItem('user_type');
  return userType === 'master' ? 'master' : 'user';
};

/**
 * Verifica se o usuário tem uma permissão específica
 */
export const hasPermission = (permission: Permission): boolean => {
  const userType = getUserType();

  if (userType === 'master') {
    return USER_TYPE_PERMISSIONS.master.includes(permission);
  }

  const storedPermissions = parseStoredPermissions();
  if (storedPermissions) {
    return storedPermissions.includes(permission);
  }

  return USER_TYPE_PERMISSIONS[userType].includes(permission);
};

/**
 * Filtra os itens de menu baseado nas permissões do usuário
 */
/**
 * O usuario logado administra a equipe da clinica?
 *
 * Lido de uma flag que `usePapelClinico` grava a partir de GET
 * /api/clinic/users/eu. Enquanto a flag nao existe (primeiro carregamento), o
 * item fica escondido: e melhor a tela aparecer um instante depois do que
 * oferecer ao atendimento uma tela que responde 403.
 */
export const podeAdministrarEquipe = (): boolean => {
  try {
    return localStorage.getItem('clinic_pode_administrar_usuarios') === 'true';
  } catch {
    return false;
  }
};

/**
 * Chave onde `useAdminPlataforma` grava se o login e o admin master.
 *
 * Mesmo mecanismo do papel clinico: a flag vem de GET /api/admin/eu (que nunca
 * responde 403) e fica em localStorage para o menu ja nascer certo.
 */
export const CHAVE_ADMIN_PLATAFORMA = 'plataforma_admin';

/** O usuario logado administra a plataforma (admin master)? */
export const podeAdministrarPlataforma = (): boolean => {
  try {
    return localStorage.getItem(CHAVE_ADMIN_PLATAFORMA) === 'true';
  } catch {
    return false;
  }
};

export interface FiltroMenuOpcoes {
  /**
   * Valor ja resolvido por `useAdminPlataforma`. Quando ausente, cai na flag do
   * localStorage — e o mesmo caminho do `requiresClinicalAdmin`, que le a flag
   * de `usePapelClinico`. Enquanto a resposta nao chegou, o item fica escondido:
   * melhor a tela aparecer um instante depois do que oferecer um 403.
   */
  ehAdminPlataforma?: boolean;
}

export const filterMenusByPermissions = (
  menuItems: MenuItem[],
  opcoes: FiltroMenuOpcoes = {},
): MenuItem[] => {
  const ehAdminPlataforma = opcoes.ehAdminPlataforma ?? podeAdministrarPlataforma();

  return menuItems.map(item => {
    const nextItem: MenuItem = {
      ...item,
      subItems: item.subItems ? item.subItems.filter(subItem => {
        if (subItem.permission && !hasPermission(subItem.permission)) {
          return false;
        }
        if (subItem.requiresPlatformAdmin && !ehAdminPlataforma) {
          return false;
        }
        return true;
      }).map(subItem => ({ ...subItem })) : undefined,
    };
    return nextItem;
  }).filter(item => {
    if (item.permission && !hasPermission(item.permission)) {
      return false;
    }

    if (item.requiresClinicalAdmin && !podeAdministrarEquipe()) {
      return false;
    }

    if (item.requiresPlatformAdmin && !ehAdminPlataforma) {
      return false;
    }

    if (item.isGroup) {
      return item.subItems && item.subItems.length > 0;
    }

    return true;
  });
};

/**
 * Obtém todas as permissões do usuário atual
 */
export const getUserPermissions = (): Permission[] => {
  const userType = getUserType();

  if (userType === 'master') {
    return USER_TYPE_PERMISSIONS.master;
  }

  const storedPermissions = parseStoredPermissions();
  if (storedPermissions) {
    return storedPermissions;
  }

  return USER_TYPE_PERMISSIONS[userType];
};

/**
 * Verifica se o usuário é master
 */
export const isUserMaster = (): boolean => {
  return getUserType() === 'master';
};

/**
 * Verifica se o usuário pode acessar configurações avançadas
 */
export const canAccessAdvancedSettings = (): boolean => {
  return hasPermission('prompt') || hasPermission('company');
};

/**
 * Debug: retorna informações do usuário atual (apenas para desenvolvimento)
 */
export const debugUserInfo = () => {
  return {
    userRole: getUserRole(),
    userType: getUserType(),
    permissions: getUserPermissions(),
    isRawData: {
      user_type: localStorage.getItem('user_type'),
      user_team: localStorage.getItem('user_team'),
      user_team_data: localStorage.getItem('user_team_data'),
      sidebar_permissions: localStorage.getItem('sidebar_permissions'),
      user_id: localStorage.getItem('user_id'),
    }
  };
};
