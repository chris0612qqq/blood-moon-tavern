// 登入資訊。token 存 localStorage（SPEC B1：Safari 擋第三方 cookie）。
import { load, remove, save } from './storage.js';

export const loadTokens = () => ({ player: load('player_token'), admin: load('admin_token') });
export const savePlayerToken = (token) => save('player_token', token);
export const saveAdminToken = (token) => save('admin_token', token);
export const clearPlayerToken = () => remove('player_token');
export const clearAdminToken = () => remove('admin_token');
export const lastName = () => load('last_name');
export const saveLastName = (name) => save('last_name', name);
