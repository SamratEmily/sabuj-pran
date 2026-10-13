import { api } from './client';

export const EMPLOYEES = {
  list: '/employees',
  attendance: '/employees/attendance',
  payroll: '/employees/payroll',
} as const;

export type AttendanceStatus = 'present' | 'absent' | 'leave' | 'late';
export const ATTENDANCE_STATUSES: AttendanceStatus[] = ['present', 'absent', 'leave', 'late'];

export interface EmployeeRecord {
  id: number;
  code: string;
  full_name: string;
  mobile: string;
  email: string;
  designation: string;
  department: string;
  joining_date: string | null;
  base_salary: string;
  is_active: boolean;
  user_id: number | null;
  username: string | null;
}

export interface AttendanceRow {
  employee_id: number;
  employee_code: string;
  employee_name: string;
  designation: string;
  department: string;
  status: AttendanceStatus;
  saved: boolean;
}

export interface AttendanceSheet {
  attendance_date: string;
  rows: AttendanceRow[];
  summary: Record<AttendanceStatus, number>;
}

export interface PayrollItem {
  id: number;
  employee_id: number;
  employee_code: string;
  employee_name: string;
  designation: string;
  base_salary: string;
  absent_days: number;
  absence_deduction: string;
  bonus: string;
  other_deduction: string;
  net_pay: string;
}

export interface PayrollRun {
  id: number;
  prl_number: string;
  month: string;
  status: 'draft' | 'paid' | 'cancelled';
  total_net: string;
  employee_count: number;
  created_by_name: string;
  created_at: string;
  paid_by_name: string | null;
  paid_at: string | null;
  payment_date: string | null;
  account_id: number | null;
  account_name: string | null;
  items: PayrollItem[];
}

export const employeesApi = {
  sheet: (date: string) => api.get<AttendanceSheet>(EMPLOYEES.attendance, { params: { attendance_date: date } }).then((r) => r.data),
  mark: (date: string, entries: { employee_id: number; status: AttendanceStatus }[]) =>
    api.put<AttendanceSheet>(EMPLOYEES.attendance, { attendance_date: date, entries }).then((r) => r.data),
  generate: (month: string) => api.post<PayrollRun>(EMPLOYEES.payroll, { month }).then((r) => r.data),
  updateRun: (id: number, items: { id: number; bonus: string; other_deduction: string }[]) =>
    api.put<PayrollRun>(`${EMPLOYEES.payroll}/${id}`, { items }).then((r) => r.data),
  pay: (id: number, data: { account_id: number; payment_date?: string }) =>
    api.post<PayrollRun>(`${EMPLOYEES.payroll}/${id}/pay`, data).then((r) => r.data),
  cancel: (id: number) => api.post<PayrollRun>(`${EMPLOYEES.payroll}/${id}/cancel`).then((r) => r.data),
};
