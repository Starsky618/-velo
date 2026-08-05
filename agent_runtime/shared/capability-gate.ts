export interface RuntimePrincipal {
  principal_id: string;
  product: "creator" | "rider";
  environment: "test" | "shadow" | "production";
  scopes: readonly string[];
}

export class CapabilityGate<TCapability extends string> {
  readonly #allowed: ReadonlySet<TCapability>;
  readonly #principal: RuntimePrincipal;
  readonly #product: RuntimePrincipal["product"];

  constructor(allowed: readonly TCapability[], product: RuntimePrincipal["product"], principal: RuntimePrincipal) {
    this.#allowed = new Set(allowed);
    this.#product = product;
    this.#principal = principal;
  }

  allows(capability: string): capability is TCapability {
    return this.#principal.product === this.#product
      && this.#principal.scopes.includes(capability)
      && this.#allowed.has(capability as TCapability);
  }

  require(capability: string): TCapability {
    if (!this.allows(capability)) {
      throw new Error(`capability denied for ${this.#principal.principal_id}: ${capability}`);
    }
    return capability;
  }
}
