import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { ShieldCheck, Lock, User, Eye, EyeOff, LogIn, UserPlus } from 'lucide-react';

function LoginPage({ onSwitchToRegister }) {
  const { login } = useAuth();
  const [usernameOrEmail, setUsernameOrEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!usernameOrEmail.trim() || !password) {
      setError('Please enter both username/email and password.');
      return;
    }

    setLoading(true);
    const result = await login(usernameOrEmail.trim(), password);
    setLoading(false);

    if (!result.success) {
      setError(result.error);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <div className="auth-header">
          <div className="auth-logo-badge">
            <ShieldCheck size={36} className="auth-icon" />
          </div>
          <h1 className="auth-title">ERA Realtor CRM</h1>
          <p className="auth-subtitle">Database & AI Orchestrator Portal</p>
        </div>

        {error && (
          <div className="auth-error-banner">
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="auth-form-group">
            <label className="auth-label">Username or Email</label>
            <div className="auth-input-wrapper">
              <User size={18} className="auth-input-icon" />
              <input
                type="text"
                className="auth-input"
                placeholder="e.g. admin or agent@bentongland.com.my"
                value={usernameOrEmail}
                onChange={(e) => setUsernameOrEmail(e.target.value)}
                autoComplete="username"
                required
              />
            </div>
          </div>

          <div className="auth-form-group">
            <label className="auth-label">Password</label>
            <div className="auth-input-wrapper">
              <Lock size={18} className="auth-input-icon" />
              <input
                type={showPassword ? 'text' : 'password'}
                className="auth-input"
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                className="auth-password-toggle"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            className="auth-submit-btn"
            disabled={loading}
          >
            {loading ? (
              <span className="auth-spinner">Authenticating...</span>
            ) : (
              <>
                <LogIn size={18} /> Sign In
              </>
            )}
          </button>
        </form>

        <div className="auth-footer">
          <p>Don't have an account?</p>
          <button
            type="button"
            className="auth-link-btn"
            onClick={onSwitchToRegister}
          >
            <UserPlus size={16} /> Create an Account
          </button>
        </div>

        <div className="auth-helper-box">
          <strong>Default Admin Credentials:</strong>
          <div className="auth-helper-row">
            <span>User: <code>admin</code></span>
            <span>Pass: <code>Admin12345!</code></span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default LoginPage;
