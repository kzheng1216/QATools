#### 安装

```
npm install react react-dom

npm install react-markdown remark-gfm

npm install codemirror @codemirror/state @codemirror/view

npm install @uiw/react-codemirror @codemirror/lang-json @codemirror/lint

npm install -g yarn

yarn add antd

yarn start
```



#### 1. yarn 命令找不到

```
# 先安装yarn（如果本机没装）
npm install -g yarn
```

#### 2. 依赖冲突 / 安装报错

```
# 强制兼容安装
yarn add antd --legacy-peer-deps
```

#### 3. 安装完启动报错，缓存清理

```
# 删除node_modules和lock文件，重装
rm -rf node_modules yarn.lock
yarn install
```

#### 4. 样式不生效

* antd v5：CSS-in-JS， **不需要 import css** ；如果写了反而冲突
* antd v4：**必须 import 'antd/dist/antd.css'**

#### 5. 导入组件报错

```
// ✅正确
import { Button } from 'antd'
// ❌错误，不要写
import Button from 'antd/Button'
```
