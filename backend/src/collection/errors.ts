/** 采集层错误体系：区分可重试瞬时故障与致命错误。 */

export class CollectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CollectionError';
  }
}

/**
 * 瞬时故障：网络异常、HTTP 5xx/429、JSON 解析失败等。
 * 与 Python 侧 _RETRYABLE 语义一致——"重试一次多半就好"，由 withRetry 处理。
 */
export class RetryableError extends CollectionError {
  constructor(message: string) {
    super(message);
    this.name = 'RetryableError';
  }
}

/**
 * 上游返回成功但数据为空。免费接口的间歇性降级（如同花顺风控）常以
 * "能解析的空包"出现，必须显式暴露并重试，而不是静默产出空洞数据。
 */
export class EmptyDataError extends RetryableError {
  constructor(message: string) {
    super(message);
    this.name = 'EmptyDataError';
  }
}

/** 雪球 token 未配置或已失效（error_code 400016）。 */
export class XqAuthError extends CollectionError {
  constructor(message: string) {
    super(message);
    this.name = 'XqAuthError';
  }
}
