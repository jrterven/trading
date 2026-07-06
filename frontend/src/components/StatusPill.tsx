import { Circle, Radio } from 'lucide-react';

interface Props {
  live: boolean;
  alpacaConfigured?: boolean;
}

export function StatusPill({ live, alpacaConfigured }: Props) {
  return (
    <div className="status-pill">
      {live ? <Radio size={15} /> : <Circle size={13} />}
      <span>{live ? 'live' : 'offline'}</span>
      <span className="status-divider" />
      <span>{alpacaConfigured ? 'Alpaca' : 'sin Alpaca'}</span>
    </div>
  );
}
