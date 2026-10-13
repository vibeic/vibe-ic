## 8.4 假如 Plugin 產生多個 sub-module

則:
- 每個 sub-module **必須**內部完整、無懸空 port、無未連接的 input
- Top module **必須**例化所有有用的 sub-module,**禁止**留 stub
- 命名空間 **不得**與 PDK std-cell 命名衝突(避免 link 階段被誤認)
