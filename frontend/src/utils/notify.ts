import type { App } from 'antd';
import axios from 'axios';

import { errorMessage } from '../api/client';

type NotificationApi = ReturnType<typeof App.useApp>['notification'];

let notification: NotificationApi | null = null;

/** Called once by <NotificationBridge> so non-component code can show themed notifications. */
export function setNotificationApi(api: NotificationApi): void {
  notification = api;
}

/** Show a backend {detail, code} error as a notification. 401s are skipped (handled by logout). */
export function notifyError(error: unknown, title = 'Something went wrong'): void {
  if (axios.isAxiosError(error) && error.response?.status === 401) return;
  const description = errorMessage(error);
  // Same key: repeated identical errors replace each other instead of stacking.
  notification?.error({ title, description, key: description, placement: 'topRight' });
}
