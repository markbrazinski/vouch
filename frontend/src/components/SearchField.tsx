import type { CSSProperties } from 'react';

export function SearchField({
  placeholder,
  style,
  fontSize = 12,
}: {
  placeholder: string;
  style?: CSSProperties;
  fontSize?: number;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: fontSize >= 13 ? 10 : 8,
        padding: fontSize >= 13 ? '11px 16px' : '7px 12px',
        background: '#EFEBE2',
        border: '1px solid rgba(0,0,0,.1)',
        borderRadius: fontSize >= 13 ? 10 : 8,
        ...style,
      }}
    >
      <span
        aria-hidden="true"
        style={{ font: `600 ${fontSize + 2}px 'IBM Plex Mono'`, color: '#A39C8D' }}
      >
        ⌕
      </span>
      <input
        type="search"
        aria-label={placeholder}
        placeholder={placeholder}
        style={{
          flex: 1,
          minWidth: 0,
          border: 'none',
          background: 'transparent',
          outline: 'none',
          font: `400 ${fontSize}px 'Public Sans'`,
          color: '#4A463E',
        }}
      />
    </div>
  );
}
