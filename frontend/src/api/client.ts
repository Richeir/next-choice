import axios from 'axios';

export const http = axios.create({
  baseURL: '/api',
  timeout: 15000,
});

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status;
    const msg =
      err?.response?.data?.message ??
      (status === 404 ? '资源不存在' : '网络请求失败，请稍后重试');
    return Promise.reject(new Error(Array.isArray(msg) ? msg.join('；') : String(msg)));
  },
);
