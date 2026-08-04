export class CapabilityGate<TCapability extends string> {
  readonly #allowed: ReadonlySet<TCapability>;

  constructor(allowed: readonly TCapability[]) {
    this.#allowed = new Set(allowed);
  }

  allows(capability: string): capability is TCapability {
    return this.#allowed.has(capability as TCapability);
  }

  require(capability: string): TCapability {
    if (!this.allows(capability)) {
      throw new Error(`capability denied: ${capability}`);
    }
    return capability;
  }
}
