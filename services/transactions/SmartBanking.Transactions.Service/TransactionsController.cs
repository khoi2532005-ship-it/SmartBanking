using Microsoft.AspNetCore.Mvc;

namespace SmartBanking.Transactions.Service
{
	[Route("Transactions")]
	public class TransactionsController : Controller
	{
		public TransactionsController()
		{

		}

		[Route("Create")]
		public IActionResult CreateTransaction()
		{
			return Ok();
		}

	}
}
