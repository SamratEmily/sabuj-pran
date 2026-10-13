import {
  AppstoreOutlined,
  BankOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  SettingOutlined,
  ShopOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  TeamOutlined,
  TruckOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { ReactNode } from 'react';

import { hasPermission } from '../hooks/usePermission';
import AuditLogPage from '../pages/admin/AuditLogPage';
import CompanySettingsPage from '../pages/admin/CompanySettingsPage';
import DocumentNumberingPage from '../pages/admin/DocumentNumberingPage';
import RolesPage from '../pages/admin/RolesPage';
import UsersPage from '../pages/admin/UsersPage';
import AdjustmentsPage from '../pages/inventory/AdjustmentsPage';
import CountsPage from '../pages/inventory/CountsPage';
import CurrentStockPage from '../pages/inventory/CurrentStockPage';
import StockLedgerPage from '../pages/inventory/StockLedgerPage';
import TransfersPage from '../pages/inventory/TransfersPage';
import ApprovalRulesPage from '../pages/approvals/ApprovalRulesPage';
import ApprovalsPage from '../pages/approvals/ApprovalsPage';
import DashboardPage from '../pages/dashboard/DashboardPage';
import AttendancePayrollPage from '../pages/employees/AttendancePayrollPage';
import EmployeesPage from '../pages/employees/EmployeesPage';
import GoodsReceiptsPage from '../pages/purchase/GoodsReceiptsPage';
import InvoicesPage from '../pages/sales/InvoicesPage';
import QuotationsPage from '../pages/sales/QuotationsPage';
import SalesOrdersPage from '../pages/sales/SalesOrdersPage';
import SalesReturnsPage from '../pages/sales/SalesReturnsPage';
import PurchaseOrdersPage from '../pages/purchase/PurchaseOrdersPage';
import CategoriesPage from '../pages/master/CategoriesPage';
import AccountLedgerPage from '../pages/money/AccountLedgerPage';
import MoneyAccountsPage from '../pages/money/MoneyAccountsPage';
import {
  CollectionsPage,
  ExpensesPage,
  IncomesPage,
  MoneyTransfersPage,
  SupplierPaymentsPage,
} from '../pages/money/VoucherPage';
import { ExpenseCategoriesPage, IncomeCategoriesPage } from '../pages/master/NamedListPage';
import PaymentMethodsPage from '../pages/master/PaymentMethodsPage';
import PriceListPage from '../pages/master/PriceListPage';
import ProductsPage from '../pages/master/ProductsPage';
import UnitsPage from '../pages/master/UnitsPage';
import WarehousesPage from '../pages/master/WarehousesPage';
import { CustomersPage, SuppliersPage } from '../pages/parties/PartiesPage';
import type { PermissionRule } from '../hooks/usePermission';

/**
 * Single source for the sidebar menu AND the app routes.
 * A leaf has `path` + `element` (the page); a group has `children`.
 */
export interface NavItem {
  key: string;
  label: string;
  icon?: ReactNode;
  path?: string;
  permission?: PermissionRule;
  element?: ReactNode;
  children?: NavItem[];
}

export const NAVIGATION: NavItem[] = [
  { key: 'dashboard', label: 'Dashboard', icon: <DashboardOutlined />, path: '/dashboard', permission: 'dashboard.view', element: <DashboardPage /> },
  {
    key: 'sales',
    label: 'Sales',
    icon: <ShoppingCartOutlined />,
    children: [
      { key: 'quotations', label: 'Quotations', path: '/sales/quotations', permission: 'quotation.view', element: <QuotationsPage /> },
      { key: 'sales-orders', label: 'Sales Orders', path: '/sales/orders', permission: 'sales_order.view', element: <SalesOrdersPage /> },
      { key: 'invoices', label: 'Invoices', path: '/sales/invoices', permission: 'invoice.view', element: <InvoicesPage /> },
      { key: 'sales-returns', label: 'Sales Returns', path: '/sales/returns', permission: 'sales_return.view', element: <SalesReturnsPage /> },
    ],
  },
  {
    key: 'purchase',
    label: 'Purchase',
    icon: <ShoppingOutlined />,
    children: [
      { key: 'purchase-orders', label: 'Purchase Orders', path: '/purchase/orders', permission: 'purchase_order.view', element: <PurchaseOrdersPage /> },
      {
        key: 'goods-receipts',
        label: 'Goods Receipts/Returns',
        path: '/purchase/receipts',
        permission: ['goods_receipt.view', 'purchase_return.view'],
        element: <GoodsReceiptsPage />,
      },
    ],
  },
  {
    key: 'inventory',
    label: 'Inventory',
    icon: <DatabaseOutlined />,
    children: [
      { key: 'current-stock', label: 'Current Stock', path: '/inventory/stock', permission: 'stock.view', element: <CurrentStockPage /> },
      { key: 'stock-ledger', label: 'Stock Ledger', path: '/inventory/ledger', permission: 'stock.view', element: <StockLedgerPage /> },
      { key: 'stock-transfers', label: 'Transfers', path: '/inventory/transfers', permission: 'stock_transfer.view', element: <TransfersPage /> },
      { key: 'stock-adjustments', label: 'Adjustments', path: '/inventory/adjustments', permission: 'stock_adjustment.view', element: <AdjustmentsPage /> },
      { key: 'stock-counts', label: 'Physical Count', path: '/inventory/counts', permission: 'stock_count.view', element: <CountsPage /> },
    ],
  },
  {
    key: 'money',
    label: 'Money',
    icon: <BankOutlined />,
    children: [
      { key: 'money-accounts', label: 'Accounts', path: '/money/accounts', permission: 'money_account.view', element: <MoneyAccountsPage /> },
      { key: 'collections', label: 'Collections', path: '/money/collections', permission: 'collection.view', element: <CollectionsPage /> },
      { key: 'supplier-payments', label: 'Supplier Payments', path: '/money/supplier-payments', permission: 'supplier_payment.view', element: <SupplierPaymentsPage /> },
      { key: 'expenses', label: 'Expenses', path: '/money/expenses', permission: 'expense.view', element: <ExpensesPage /> },
      { key: 'income', label: 'Income', path: '/money/income', permission: 'income.view', element: <IncomesPage /> },
      { key: 'money-transfers', label: 'Transfers', path: '/money/transfers', permission: 'money_transfer.view', element: <MoneyTransfersPage /> },
      { key: 'account-ledger', label: 'Account Ledger', path: '/money/ledger', permission: 'money_account.view', element: <AccountLedgerPage /> },
    ],
  },
  { key: 'customers', label: 'Customers', icon: <UserOutlined />, path: '/customers', permission: 'customer.view', element: <CustomersPage /> },
  { key: 'suppliers', label: 'Suppliers', icon: <TruckOutlined />, path: '/suppliers', permission: 'supplier.view', element: <SuppliersPage /> },
  {
    key: 'employees',
    label: 'Employees',
    icon: <TeamOutlined />,
    children: [
      { key: 'employee-list', label: 'Employees', path: '/employees', permission: 'employee.view', element: <EmployeesPage /> },
      {
        key: 'attendance-payroll',
        label: 'Attendance & Payroll',
        path: '/employees/payroll',
        permission: ['attendance.view', 'payroll.view'],
        element: <AttendancePayrollPage />,
      },
    ],
  },
  {
    key: 'master',
    label: 'Master Data',
    icon: <AppstoreOutlined />,
    children: [
      { key: 'products', label: 'Products', path: '/master/products', permission: 'product.view', element: <ProductsPage /> },
      { key: 'categories', label: 'Product Categories', path: '/master/categories', permission: 'category.view', element: <CategoriesPage /> },
      { key: 'units', label: 'Units', path: '/master/units', permission: 'unit.view', element: <UnitsPage /> },
      { key: 'price-list', label: 'Price List', path: '/master/prices', permission: 'price.view', element: <PriceListPage /> },
      { key: 'warehouses', label: 'Warehouses', path: '/master/warehouses', permission: 'warehouse.view', element: <WarehousesPage /> },
      { key: 'expense-categories', label: 'Expense Categories', path: '/master/expense-categories', permission: 'expense_category.view', element: <ExpenseCategoriesPage /> },
      { key: 'income-categories', label: 'Income Categories', path: '/master/income-categories', permission: 'income_category.view', element: <IncomeCategoriesPage /> },
      { key: 'payment-methods', label: 'Payment Methods', path: '/master/payment-methods', permission: 'payment_method.view', element: <PaymentMethodsPage /> },
    ],
  },
  {
    key: 'admin',
    label: 'Administration',
    icon: <SettingOutlined />,
    children: [
      { key: 'users', label: 'Users', path: '/admin/users', permission: 'user.view', element: <UsersPage /> },
      { key: 'roles', label: 'Roles & Permissions', path: '/admin/roles', permission: 'role.view', element: <RolesPage /> },
      { key: 'approval-rules', label: 'Approval Rules', path: '/admin/approval-rules', permission: 'approval_rule.view', element: <ApprovalRulesPage /> },
      { key: 'approvals', label: 'Pending Approvals', path: '/admin/approvals', permission: 'approval.view', element: <ApprovalsPage /> },
      { key: 'audit-log', label: 'Audit Log', path: '/admin/audit-log', permission: 'audit_log.view', element: <AuditLogPage /> },
      { key: 'numbering', label: 'Document Numbering', path: '/admin/numbering', permission: 'document_sequence.view', element: <DocumentNumberingPage /> },
      { key: 'company', label: 'Company Settings', path: '/admin/company', permission: 'company_setting.view', element: <CompanySettingsPage /> },
    ],
  },
];

export const HOME_ICON = <ShopOutlined />;

/** Items the user may see. Groups with no visible children are dropped. */
export function filterNavigation(items: NavItem[], permissions: ReadonlySet<string>): NavItem[] {
  return items.flatMap((item) => {
    if (item.children) {
      const children = filterNavigation(item.children, permissions);
      return children.length ? [{ ...item, children }] : [];
    }
    return hasPermission(permissions, item.permission) ? [item] : [];
  });
}

/** Every leaf (page) in the tree. */
export function navLeaves(items: NavItem[] = NAVIGATION): NavItem[] {
  return items.flatMap((item) => (item.children ? navLeaves(item.children) : [item]));
}
