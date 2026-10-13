import { App } from 'antd';
import { useEffect } from 'react';

import { setNotificationApi } from '../utils/notify';

/** Hands the themed notification API (from <App>) to the global error handler. */
export default function NotificationBridge() {
  const { notification } = App.useApp();
  useEffect(() => setNotificationApi(notification), [notification]);
  return null;
}
