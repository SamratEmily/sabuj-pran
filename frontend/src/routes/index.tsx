import { Result } from 'antd';
import { createBrowserRouter } from 'react-router';
import type { RouteObject } from 'react-router';

import AppLayout from '../layouts/AppLayout';
import AuthLayout from '../layouts/AuthLayout';
import ForgotPasswordPage from '../pages/auth/ForgotPasswordPage';
import LoginPage from '../pages/auth/LoginPage';
import ResetPasswordPage from '../pages/auth/ResetPasswordPage';
import HomePage from '../pages/home/HomePage';
import StockDocumentPage from '../pages/inventory/StockDocumentPage';
import PurchaseOrderPage from '../pages/purchase/PurchaseOrderPage';
import InvoicePage from '../pages/sales/InvoicePage';
import SalesOrderPage from '../pages/sales/SalesOrderPage';
import ChangePasswordPage from '../pages/profile/ChangePasswordPage';
import StatementPage from '../pages/parties/StatementPage';
import ProfilePage from '../pages/profile/ProfilePage';
import { CHANGE_PASSWORD_PATH, GuestOnlyRoute, ProtectedRoute, RequirePermission } from './guards';
import { navLeaves } from './navigation';

// One route per menu leaf, guarded by the same permission that shows the menu entry.
const moduleRoutes: RouteObject[] = navLeaves().map((leaf) => ({
  path: leaf.path,
  element: (
    <RequirePermission permission={leaf.permission}>
      {leaf.element}
    </RequirePermission>
  ),
}));

export const router = createBrowserRouter([
  {
    element: <AuthLayout />,
    children: [
      { path: '/login', element: <GuestOnlyRoute><LoginPage /></GuestOnlyRoute> },
      { path: '/forgot-password', element: <ForgotPasswordPage /> },
      { path: '/reset-password', element: <ResetPasswordPage /> },
    ],
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { path: '/', element: <HomePage /> },
          { path: '/profile', element: <ProfilePage /> },
          { path: CHANGE_PASSWORD_PATH, element: <ChangePasswordPage /> },
          ...moduleRoutes,
          {
            path: '/purchase/orders/:id',
            element: (
              <RequirePermission permission="purchase_order.view">
                <PurchaseOrderPage />
              </RequirePermission>
            ),
          },
          {
            path: '/sales/orders/:id',
            element: (
              <RequirePermission permission="sales_order.view">
                <SalesOrderPage />
              </RequirePermission>
            ),
          },
          {
            path: '/sales/invoices/:id',
            element: (
              <RequirePermission permission="invoice.view">
                <InvoicePage />
              </RequirePermission>
            ),
          },
          ...([
            ['transfers', 'stock_transfer.view'],
            ['adjustments', 'stock_adjustment.view'],
            ['counts', 'stock_count.view'],
          ] as const).map(([kind, permission]) => ({
            path: `/inventory/${kind}/:id`,
            element: (
              <RequirePermission permission={permission}>
                <StockDocumentPage key={kind} kind={kind} />
              </RequirePermission>
            ),
          })),
          ...(['customers', 'suppliers'] as const).map((kind) => ({
            path: `/${kind}/:id/statement`,
            element: (
              <RequirePermission permission="party_statement.view">
                <StatementPage key={kind} kind={kind} />
              </RequirePermission>
            ),
          })),
          { path: '*', element: <Result status="404" title="Page not found" /> },
        ],
      },
    ],
  },
]);
