import { useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import { IS_TAURI } from '../config';

export default function DbPicker() {
  const [path, setPath] = useState<string | null>(null);

  if (!IS_TAURI) return null;

  const pick = async () => {
    const selected = await open({
      multiple: false,
      directory: false,
      filters: [{ name: 'SQLite', extensions: ['db'] }],
    });
    if (typeof selected === 'string') {
      await invoke('set_db_path', { path: selected });
      setPath(selected);
      alert('已保存数据库路径，请重启应用生效。');
    }
  };

  return (
    <button type="button" className="nav-link" onClick={pick}>
      数据源{path ? ` · ${path.split('/').pop()}` : ''}
    </button>
  );
}
