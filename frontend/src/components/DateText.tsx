import dayjs from 'dayjs';

interface Props {
  value: string | null | undefined;
  withTime?: boolean;
}

export const DATE_FORMAT = 'DD MMM YYYY';
export const DATETIME_FORMAT = 'DD MMM YYYY, hh:mm A';

/** ISO date/datetime from the API, formatted for display. */
export default function DateText({ value, withTime }: Props) {
  if (!value) return <>—</>;
  const d = dayjs(value);
  return <>{d.isValid() ? d.format(withTime ? DATETIME_FORMAT : DATE_FORMAT) : value}</>;
}
