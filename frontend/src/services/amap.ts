import AMapLoader from '@amap/amap-jsapi-loader'

// 当前项目只使用这几个SDK能力，定义最小接口即可。

// 为MarkerInstance接口注册一个事件，当点击时执行handler函数
export interface MarkerInstance {
  on(event: 'click', handler: () => void): void
}

// 定义整个地图事件可以执行哪些操作
export interface MapInstance {
  add(markers: MarkerInstance[]): void
  remove(markers: MarkerInstance[]): void
  setFitView(): void
  destroy(): void
}

// 定义整个高德地图SDK应该提供哪些功能，以及如何创建地图对象和地图标记对象
export interface MapSDK {
  // Map构造器，使用new创建地图
  Map: new (
    container: HTMLElement,
    options: {
      zoom: number
      viewMode: string
    },
  ) => MapInstance

  // Marker构造器，使用new创建地图标记
  Marker: new (options: {
    position: [number, number]
    content: HTMLElement
    title: string
    anchor: string
  }) => MarkerInstance
}

// 告诉TypeScript，window对象上可存在_AMapSecurityConfig属性，用于保存高德地图SDK的安全配置
declare global {
  interface Window {
    _AMapSecurityConfig?: {
      securityJsCode: string
    }
  }
}

// 定义一个变量，该变量只可能保存两种值，“一个最终可能得到地图SDK的异步任务”或者空值
let sdkPromise: Promise<MapSDK> | null = null

// SDK加载过程共享，但每个地图组件仍有自己的地图实例。
// 下面定义SDK加载函数，返回一个Promise对象，最终可能得到地图SDK对象。
export function loadMapSDK(): Promise<MapSDK> {
  const key =
    import.meta.env.VITE_AMAP_JS_KEY?.trim()

  const securityJsCode =
    import.meta.env.VITE_AMAP_SECURITY_JS_CODE?.trim()

  if (!key || !securityJsCode) {
    return Promise.reject(
      new Error(
        '地图尚未配置，请填写frontend/.env.local中的'
        + '网页地图Key和安全密钥，然后重启前端。',
      ),
    )
  }

  if (!sdkPromise) {
    window._AMapSecurityConfig = {
      securityJsCode,
    }

    sdkPromise = AMapLoader.load({
      key,
      version: '2.0',
    }).then((sdk: unknown) => sdk as MapSDK)
  }

  return sdkPromise
}

