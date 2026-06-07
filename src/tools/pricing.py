"""
This tool is mainly for demonstration or debugging purposes.
It is lighter then the heavy vision tool etc.
"""
from smolagents import tool

@tool
def calculate_margin(purchase_price: float, selling_price: float) -> str:
    """
    Calculates the profit margin and absolute profit for a resale item.

    Args:
        purchase_price: The price the item was bought for, in euros.
        selling_price: The price the item will be sold for, in euros.
    """
    if purchase_price <= 0:
        return "Error: purchase_price must be greater than 0."

    profit = selling_price - purchase_price
    margin = (profit / purchase_price) * 100
    return (
        f"Purchase: {purchase_price:.2f} €, "
        f"Selling: {selling_price:.2f} €, "
        f"Profit: {profit:.2f} €, "
        f"Margin: {margin:.1f}%"
    )
