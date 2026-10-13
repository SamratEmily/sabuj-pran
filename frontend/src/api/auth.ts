import { api } from './client';

export interface AuthUser {
  id: number;
  full_name: string;
  username: string;
  email: string | null;
  mobile: string | null;
  role: string;
  permissions: string[];
  must_change_password: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export interface ForgotPasswordResponse {
  message: string;
  reset_token?: string;
}

export interface ProfileInput {
  full_name: string;
  email?: string | null;
  mobile?: string | null;
}

export const authApi = {
  login: (identifier: string, password: string) =>
    api.post<LoginResponse>('/auth/login', { identifier, password }).then((r) => r.data),
  me: () => api.get<AuthUser>('/auth/me').then((r) => r.data),
  updateMe: (data: ProfileInput) => api.put<AuthUser>('/auth/me', data).then((r) => r.data),
  changePassword: (current_password: string, new_password: string) =>
    api.post('/auth/change-password', { current_password, new_password }).then((r) => r.data),
  forgotPassword: (identifier: string) =>
    api.post<ForgotPasswordResponse>('/auth/forgot-password', { identifier }).then((r) => r.data),
  resetPassword: (token: string, new_password: string) =>
    api.post('/auth/reset-password', { token, new_password }).then((r) => r.data),
  logout: () => api.post('/auth/logout').then((r) => r.data),
};
