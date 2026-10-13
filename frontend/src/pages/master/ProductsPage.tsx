import { Col, Form, Input, InputNumber, Row, Select, Tag, Typography } from 'antd';

import { MASTER, PRODUCT_TYPE_COLORS, PRODUCT_TYPE_LABELS, useLookups } from '../../api/master';
import type { ProductRecord, ProductType } from '../../api/master';
import CrudPage from '../../components/CrudPage';
import MoneyText from '../../components/MoneyText';
import QtyText from '../../components/QtyText';

interface ProductForm {
  code?: string;
  name: string;
  category_id: number;
  unit_id: number;
  product_type: ProductType;
  purchase_price: string;
  reorder_level: string;
  description: string;
  initial_price?: string | null;
}

const TYPE_OPTIONS = Object.entries(PRODUCT_TYPE_LABELS).map(([value, label]) => ({ value, label }));

/** Active options, plus the record's current (possibly inactive) choice so edits still show it. */
function withCurrent(options: { label: string; value: number }[], id?: number, label?: string) {
  return id && !options.some((o) => o.value === id) ? [...options, { label: `${label} (inactive)`, value: id }] : options;
}

export default function ProductsPage() {
  const lookups = useLookups();
  const categoryOptions = (lookups.data?.categories ?? []).map((c) => ({ label: c.name, value: c.id }));
  const unitOptions = (lookups.data?.units ?? []).map((u) => ({ label: `${u.name} (${u.short_code})`, value: u.id }));

  return (
    <CrudPage<ProductRecord, ProductForm>
      title="Product List"
      endpoint={MASTER.products}
      permission="product"
      itemName="product"
      searchPlaceholder="Search name or code"
      formWidth={640}
      invalidates={[MASTER.prices]}
      filters={[
        { name: 'category_id', label: 'Category', options: categoryOptions },
        { name: 'product_type', label: 'Type', options: TYPE_OPTIONS },
      ]}
      initialValues={{ product_type: 'finished_good', purchase_price: '0', reorder_level: '0', description: '' }}
      errorFields={{
        NAME_TAKEN: 'name',
        CODE_TAKEN: 'code',
        INVALID_CATEGORY: 'category_id',
        INACTIVE_CATEGORY: 'category_id',
        INVALID_UNIT: 'unit_id',
        INACTIVE_UNIT: 'unit_id',
      }}
      toFormValues={(p) => ({
        code: p.code,
        name: p.name,
        category_id: p.category_id,
        unit_id: p.unit_id,
        product_type: p.product_type,
        purchase_price: p.purchase_price,
        reorder_level: p.reorder_level,
        description: p.description,
      })}
      columns={[
        { title: 'Code', dataIndex: 'code', width: 100, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
        { title: 'Name', dataIndex: 'name' },
        { title: 'Category', dataIndex: 'category_name' },
        {
          title: 'Type',
          dataIndex: 'product_type',
          render: (t: ProductType) => <Tag color={PRODUCT_TYPE_COLORS[t]}>{PRODUCT_TYPE_LABELS[t]}</Tag>,
        },
        { title: 'Unit', dataIndex: 'unit_code' },
        { title: <span style={{ display: 'block', textAlign: 'right' }}>Purchase price</span>, dataIndex: 'purchase_price', render: (v: string) => <MoneyText value={v} scale={4} /> },
        {
          title: <span style={{ display: 'block', textAlign: 'right' }}>Sale price</span>,
          dataIndex: 'current_price',
          render: (v: string | null) => (v ? <MoneyText value={v} strong /> : <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'right' }}>Not set</Typography.Text>),
        },
        { title: <span style={{ display: 'block', textAlign: 'right' }}>Reorder level</span>, dataIndex: 'reorder_level', render: (v: string) => <QtyText value={v} /> },
      ]}
      renderForm={({ record }) => (
        <Row gutter={16}>
          <Col xs={24} md={10}>
            <Form.Item
              name="code"
              label="Code"
              extra={record ? undefined : 'Leave blank to generate (P-0001…).'}
              rules={[{ pattern: /^[A-Za-z0-9/_.-]{1,30}$/, message: 'Up to 30 letters, digits, / _ . -' }]}
            >
              <Input placeholder={record ? undefined : 'Auto'} />
            </Form.Item>
          </Col>
          <Col xs={24} md={14}>
            <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, message: 'Enter a name' }, { max: 150 }]}>
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="category_id" label="Category" rules={[{ required: true, message: 'Choose a category' }]}>
              <Select
                showSearch={{ optionFilterProp: 'label' }}
                loading={lookups.isPending}
                options={withCurrent(categoryOptions, record?.category_id, record?.category_name)}
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="unit_id" label="Unit" rules={[{ required: true, message: 'Choose a unit' }]}>
              <Select
                showSearch={{ optionFilterProp: 'label' }}
                loading={lookups.isPending}
                options={withCurrent(unitOptions, record?.unit_id, record?.unit_name)}
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="product_type" label="Type" rules={[{ required: true }]}>
              <Select options={TYPE_OPTIONS} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="purchase_price" label="Purchase price (default cost)" rules={[{ required: true, message: 'Enter a cost (0 if unknown)' }]}>
              <InputNumber<string> stringMode min="0" precision={4} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="reorder_level" label="Reorder level" rules={[{ required: true, message: 'Enter a level (0 for none)' }]}>
              <InputNumber<string> stringMode min="0" precision={3} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          {!record && (
            <Col xs={24} md={12}>
              <Form.Item name="initial_price" label="Sale price" extra="Optional. Effective from today; later changes go in the Price List.">
                <InputNumber<string> stringMode min="0" precision={2} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          )}
          <Col xs={24}>
            <Form.Item name="description" label="Description" rules={[{ max: 500 }]}>
              <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
            </Form.Item>
          </Col>
        </Row>
      )}
    />
  );
}
