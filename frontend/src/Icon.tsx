const paths = {
  mark: 'M3 12 8 4h10l3 5-5 8H6l-3-5Zm5 0h8m-4-4v8m-5 4h10',
  requests: 'M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2M8 2h8v5H8zm0 10h8m-8 5h6',
  people: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-4m-3-12a4 4 0 0 1 0 8M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
  branch: 'M3 21h18M5 21V7l7-4v18m0-13h7v13M8 9v1m0 3v1m0 3v1m7-7v1m0 3v1',
  logout: 'M10 17l5-5-5-5m5 5H3m10-9h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6',
  arrow: 'M4 12h15m-6-6 6 6-6 6',
  back: 'M20 12H5m6-6-6 6 6 6',
  refresh: 'M20 7v5h-5M4 17v-5h5m-4.2-3a8 8 0 0 1 13.8-3L20 8M4 16l1.4 2a8 8 0 0 0 13.8-3',
  plus: 'M12 5v14M5 12h14',
  search: 'M15.5 15.5 21 21m-3-10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z',
  pin: 'M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Zm-5 0a3 3 0 1 0-6 0 3 3 0 0 0 6 0Z',
  check: 'm5 12 4 4L19 6',
  tool: 'M14.5 6.5 18 3a6 6 0 0 0-7.6 7.6L3 18a2 2 0 0 0 3 3l7.4-7.4A6 6 0 0 0 21 6l-3.5 3.5z',
};

export function Icon({ name, size = 20 }: { name: keyof typeof paths; size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24"
    fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round">
    <path d={paths[name]} />
  </svg>;
}
