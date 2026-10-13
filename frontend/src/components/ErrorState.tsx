import { Alert, Button } from 'antd';

import { errorMessage } from '../api/client';

interface Props {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}

/** Standard inline error block for a failed load. */
export default function ErrorState({ error, onRetry, title = 'Could not load data' }: Props) {
  return (
    <Alert
      type="error"
      showIcon
      title={title}
      description={errorMessage(error)}
      action={onRetry && <Button size="small" onClick={onRetry}>Retry</Button>}
      style={{ marginBottom: 16 }}
    />
  );
}
