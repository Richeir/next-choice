import axios from 'axios';
import { API_BASE_URL } from '../config';

export const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
});

/** 归一化后的接口错误：message 面向用户，status 供调用方按状态码分支。 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status;
    const msg =
      err?.response?.data?.message ??
      (status === 404 ? '资源不存在' : '网络请求失败，请稍后重试');
    return Promise.reject(
      new ApiError(Array.isArray(msg) ? msg.join('；') : String(msg), status),
    );
  },
);
