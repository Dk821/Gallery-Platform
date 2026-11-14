import type { ReactNode } from "react";

function Svg({ children }: { children: ReactNode }) {
  return (
    <svg className="sa-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const IconDashboard = () => (
  <Svg>
    <rect x="3" y="3" width="7.5" height="9" rx="1.5" />
    <rect x="13.5" y="3" width="7.5" height="5" rx="1.5" />
    <rect x="13.5" y="11" width="7.5" height="10" rx="1.5" />
    <rect x="3" y="15" width="7.5" height="6" rx="1.5" />
  </Svg>
);
export const IconStudios = () => (
  <Svg>
    <path d="M3 21h18M5 21V9l7-5 7 5v12" />
    <path d="M9 21v-6h6v6" />
  </Svg>
);
export const IconLog = () => (
  <Svg>
    <path d="M8 4h9a2 2 0 012 2v14l-3-2-3 2-3-2-3 2V6a2 2 0 012-2z" />
    <path d="M9 9h6M9 13h6" />
  </Svg>
);
export const IconSettings = () => (
  <Svg>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 00.34 1.87l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.7 1.7 0 00-1.87-.34 1.7 1.7 0 00-1.03 1.56V21a2 2 0 11-4 0v-.09a1.7 1.7 0 00-1.11-1.56 1.7 1.7 0 00-1.87.34l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.7 1.7 0 00.34-1.87 1.7 1.7 0 00-1.56-1.03H3a2 2 0 110-4h.09a1.7 1.7 0 001.56-1.11 1.7 1.7 0 00-.34-1.87l-.06-.06a2 2 0 112.83-2.83l.06.06a1.7 1.7 0 001.87.34h.01a1.7 1.7 0 001.03-1.56V3a2 2 0 114 0v.09a1.7 1.7 0 001.03 1.56h.01a1.7 1.7 0 001.87-.34l.06-.06a2 2 0 112.83 2.83l-.06.06a1.7 1.7 0 00-.34 1.87v.01a1.7 1.7 0 001.56 1.03H21a2 2 0 110 4h-.09a1.7 1.7 0 00-1.56 1.03z" />
  </Svg>
);
export const IconLogout = () => (
  <Svg>
    <path d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l3 3m0 0l-3 3m3-3H3" />
  </Svg>
);
export const IconCopy = () => (
  <Svg>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V6a2 2 0 012-2h9" />
  </Svg>
);
export const IconSearch = () => (
  <Svg>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.5-3.5" />
  </Svg>
);
export const IconWarn = () => (
  <Svg>
    <path d="M12 3l10 18H2L12 3z" />
    <path d="M12 10v5M12 18.2v.1" />
  </Svg>
);

export const IconUsers = () => (
  <Svg>
    <path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
  </Svg>
);
export const IconAlbums = () => (
  <Svg>
    <rect x="3" y="3" width="18" height="18" rx="2.5" />
    <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" />
    <path d="M21 15l-5-5L5 21" />
  </Svg>
);
export const IconMedia = () => (
  <Svg>
    <rect x="3" y="3" width="18" height="18" rx="2.5" />
    <path d="M3 9h18M9 21V9" />
  </Svg>
);
export const IconChevronDown = () => (
  <svg className="sa-profile__caret" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
    <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
  </svg>
);

export const IconDownload = () => (
  <Svg>
    <path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 20h14" />
  </Svg>
);
export const IconRefresh = () => (
  <Svg>
    <path d="M20 11a8 8 0 10-2.3 5.7M20 4v7h-7" />
  </Svg>
);
export const IconUpload = () => (
  <Svg>
    <path d="M12 20V9M7.5 13.5L12 9l4.5 4.5M5 4h14" />
  </Svg>
);
export const IconCheck = () => (
  <Svg>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
);

export const IconStorage = () => (
  <Svg>
    <ellipse cx="12" cy="6" rx="8" ry="3" />
    <path d="M4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6" />
  </Svg>
);
export const IconKey = () => (
  <Svg>
    <circle cx="8" cy="15" r="4" />
    <path d="M11 12l8-8M16 7l3 3M14 9l2 2" />
  </Svg>
);
