import React from 'react';
import { createPortal } from 'react-dom';
import { X, type LucideIcon } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import { agentiveIconButtonClass } from './AgentiveUI.tsx';

/**
 * Casca de modal usada pelas telas de cadastro da clínica.
 *
 * Existe para que Procedimentos e Profissionais não dupliquem a mesma estrutura
 * de overlay + cabeçalho + rodapé. Segue o padrão já usado em CompanyConfig.tsx
 * (createPortal no body, fundo brand/55 com blur, borda e superfície por tema).
 */
interface ClinicaModalProps {
  children: React.ReactNode;
  description?: string;
  footer?: React.ReactNode;
  icon: LucideIcon;
  onClose: () => void;
  open: boolean;
  title: string;
  wide?: boolean;
}

const ClinicaModal: React.FC<ClinicaModalProps> = ({
  children,
  description,
  footer,
  icon: Icon,
  onClose,
  open,
  title,
  wide = false,
}) => {
  const { isDark } = useTheme();

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Fechar modal"
        className="fixed inset-0 cursor-default bg-brand/55 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        className={`relative z-[10000] flex max-h-[92vh] w-full flex-col overflow-hidden rounded-2xl border shadow-[0_24px_70px_rgba(17,17,17,0.28)] ${
          wide ? 'max-w-3xl' : 'max-w-xl'
        } ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}
      >
        <div className={`flex items-start justify-between gap-4 border-b p-5 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
          <div className="flex min-w-0 items-start gap-3">
            <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
              <Icon className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold leading-tight">{title}</h2>
              {description && (
                <p className={`mt-1 text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>{description}</p>
              )}
            </div>
          </div>
          <button type="button" onClick={onClose} className={agentiveIconButtonClass(isDark)} aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="overflow-y-auto p-5">{children}</div>

        {footer && (
          <div className={`flex flex-col-reverse gap-2 border-t p-5 sm:flex-row sm:justify-end ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};

export default ClinicaModal;
