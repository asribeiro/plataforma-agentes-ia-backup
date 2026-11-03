import { render, screen } from '@testing-library/react';
import App from './App';

describe('App smoke test', () => {
  it('renders the login screen on the public route', () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: /acesse sua conta/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Email$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Senha$/i)).toBeInTheDocument();
  });
});
