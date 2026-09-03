using System.Collections.Generic;
using Microsoft.AspNetCore.Mvc;

namespace SmartBanking.Service.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class TransactionsController : ControllerBase
    {
        [HttpGet]
        public IActionResult Get()
        {
            var sample = new List<object>
            {
                new { transaction_id = 1, account_id = 1001, amount = 250.00, currency = "AUD", type = "Deposit", category = "Salary", date = "2024-08-01" },
                new { transaction_id = 2, account_id = 1001, amount = -50.25, currency = "AUD", type = "Withdrawal", category = "Groceries", date = "2024-08-02" },
                new { transaction_id = 3, account_id = 1002, amount = -120.00, currency = "AUD", type = "Transfer", category = "Rent", date = "2024-08-03" }
            };

            return Ok(sample);
        }
    }
}
