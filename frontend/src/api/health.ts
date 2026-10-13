import { api } from './client';

export interface Health {
  status: string;
  db: boolean;
}

export async function getHealth(): Promise<Health> {
  const { data } = await api.get<Health>('/health');
  return data;
}
