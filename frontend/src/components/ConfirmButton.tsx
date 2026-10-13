import { Button, Popconfirm } from 'antd';
import type { ButtonProps } from 'antd';
import { useState } from 'react';
import type { ReactNode } from 'react';

interface Props extends Omit<ButtonProps, 'onClick'> {
  /** Question shown in the confirmation popup. */
  confirm: ReactNode;
  description?: ReactNode;
  okText?: string;
  /** May return a promise; the button shows a spinner until it settles. */
  onConfirm: () => unknown;
}

/** A button that asks for confirmation before running an action. */
export default function ConfirmButton({ confirm, description, okText = 'Yes', onConfirm, loading, ...button }: Props) {
  const [running, setRunning] = useState(false);
  const handleConfirm = async () => {
    setRunning(true);
    try {
      await onConfirm();
    } catch {
      // errors are shown by the global mutation error handler
    } finally {
      setRunning(false);
    }
  };
  return (
    <Popconfirm
      title={confirm}
      description={description}
      okText={okText}
      cancelText="No"
      onConfirm={handleConfirm}
      okButtonProps={{ danger: button.danger }}
    >
      <Button {...button} loading={running || loading} />
    </Popconfirm>
  );
}
