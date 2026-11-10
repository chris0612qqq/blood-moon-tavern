// 登入資訊。token 存 localStorage（SPEC B1：Safari 擋第三方 cookie）。
import { load, remove, save } from './storage.js';

export const loadTokens = () => ({ player: load('player_token'), admin: load('admin_token') });
export const savePlayerToken = (token) => save('player_token', token);
export const saveAdminToken = (token) => save('admin_token', token);
export const clearPlayerToken = () => remove('player_token');
export const clearAdminToken = () => remove('admin_token');
export const lastName = () => load('last_name');
// 語音名字與代號（SPEC v4.40）也記住，下次一起帶入
export const lastSpoken = () => load('last_spoken');
export const lastMark = () => load('last_mark');
export function saveLastNames(name, spoken, mark) {
  save('last_name', name);
  save('last_spoken', spoken);
  save('last_mark', mark);
}
