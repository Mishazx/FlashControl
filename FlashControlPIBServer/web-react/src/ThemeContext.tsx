import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';

type ThemeMode = 'light' | 'dark';
type ThemePref = 'auto' | ThemeMode;

interface ThemeCtx {
  mode: ThemeMode;
  pref: ThemePref;
  setPref: (p: ThemePref) => void;
}

const Ctx = createContext<ThemeCtx>({ mode: 'dark', pref: 'auto', setPref: () => {} });

function resolveSystem(): ThemeMode {
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function applyTheme(mode: ThemeMode) {
  const root = document.documentElement;
  const has = root.classList.contains('light');
  if (mode === 'light' && !has) root.classList.add('light');
  else if (mode === 'dark' && has) root.classList.remove('light');
  root.setAttribute('color-scheme', mode);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(() => {
    const saved = localStorage.getItem('fc-theme');
    if (saved === 'light' || saved === 'dark') return saved;
    return 'auto';
  });

  const [mode, setMode] = useState<ThemeMode>(() => (pref === 'auto' ? resolveSystem() : pref));

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: light)');

    const update = () => {
      const next = pref === 'auto' ? (mq.matches ? 'light' : 'dark') : pref;
      setMode(next);
    };
    update();

    if (pref === 'auto') {
      mq.addEventListener('change', update);
      return () => mq.removeEventListener('change', update);
    }
  }, [pref]);

  useEffect(() => {
    applyTheme(mode);
  }, [mode]);

  const setPref = (p: ThemePref) => {
    setPrefState(p);
    if (p === 'auto') localStorage.removeItem('fc-theme');
    else localStorage.setItem('fc-theme', p);
  };

  return <Ctx.Provider value={{ mode, pref, setPref }}>{children}</Ctx.Provider>;
}

export function useTheme() {
  return useContext(Ctx);
}
